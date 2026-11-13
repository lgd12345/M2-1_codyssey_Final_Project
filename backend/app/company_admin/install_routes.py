import base64
import hashlib
import hmac
import os
from pathlib import Path
import re

from fastapi import APIRouter,Depends,Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel,ConfigDict,Field,SecretStr,StrictBool

from app.auth.deps import require_operator
from app.company_admin import install_core as core
from app.company_admin.routes import SafeRoute,write_session

class InstallBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    approval_code:SecretStr=Field(min_length=43,max_length=128)
    target_fingerprint:str=Field(pattern='^[0-9a-f]{64}$')
    release_id:str=Field(pattern='^[0-9a-f]{32}$')
    confirmed:StrictBool


def build_router(engine, slug, template):
    router = APIRouter(prefix='/api/v1/companies/'+slug,route_class=SafeRoute,include_in_schema=False)


    def grant_for(request,session):
        return engine.read_grant(session,request.headers.get('host',''))


    @router.get('')
    def page(request:Request,session=Depends(require_operator)):
        grant_for(request,session)
        html = Path(__file__).with_name(template).read_text(encoding='utf-8')
        def hashes(tag):
            return ' '.join("'sha256-"+base64.b64encode(hashlib.sha256(text.encode()).digest()).decode()+"'"
                            for text in re.findall('<'+tag+'>(.*?)</'+tag+'>',html,re.S))
        return HTMLResponse(html,headers={
            'Content-Security-Policy':"default-src 'none'; script-src "+hashes('script')+"; style-src "+hashes('style')+"; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
            'Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY',
        })


    @router.get('/status')
    def status(request:Request,session=Depends(require_operator)):
        grant = grant_for(request,session)
        return engine.inspect_installation(core.runtime_dsn(os.environ),grant,session)


    @router.post('/apply')
    def apply(body:InstallBody,request:Request,session=Depends(write_session)):
        grant = grant_for(request,session)
        if request.headers.get('origin')!=grant['origin']:
            raise core.InstallError()
        if (not body.confirmed or not hmac.compare_digest(body.release_id,grant['release_id'])
                or not hmac.compare_digest(hashlib.sha256(body.approval_code.get_secret_value().encode()).hexdigest(),grant['approval_sha256'])):
            raise core.InstallError()
        return engine.apply_installation(core.runtime_dsn(os.environ),grant,session,body.target_fingerprint)
    return router


router = build_router(core, 'installation', 'installation.html')
