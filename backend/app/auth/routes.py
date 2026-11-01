from __future__ import annotations

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth.deps import (
    COOKIE_NAME, check_origin, cookie_secure, current_session, database, require_csrf,
)
from app.auth.service import (
    AuthError, SESSION_INTERVAL, SessionInfo, authenticate, create_session, revoke_session,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
SESSION_MAX_AGE = 7 * 24 * 3600


class LoginRequest(BaseModel):
    login_id: str = Field(min_length=1, max_length=500)
    password: str = Field(min_length=1, max_length=1000)


def _state(session: SessionInfo | None) -> dict:
    if session is None:
        return {"authenticated": False, "user": None, "csrf_token": None}
    return {"authenticated": True, "user": session.user.public(), "csrf_token": session.csrf_token}


@router.get("/me")
def me(request: Request):
    return _state(current_session(request))


@router.post("/login")
def login(body: LoginRequest, request: Request, response: Response):
    check_origin(request)
    client = request.client.host if request.client else "unknown"
    with database() as connection:
        try:
            user = authenticate(connection, body.login_id, body.password, client)
        except AuthError:
            connection.commit()  # keep the failure record that drives throttling
            raise
        token, csrf = create_session(connection, user.id, replacing=request.cookies.get(COOKIE_NAME))
    response.set_cookie(COOKIE_NAME, token, max_age=SESSION_MAX_AGE, httponly=True,
                        samesite="lax", secure=cookie_secure(), path="/")
    return {"authenticated": True, "user": user.public(), "csrf_token": csrf}


@router.post("/logout", status_code=204)
def logout(request: Request, _session: SessionInfo = Depends(require_csrf)):
    with database() as connection:
        revoke_session(connection, request.cookies.get(COOKIE_NAME))
    response = Response(status_code=204)
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="lax", secure=cookie_secure())
    return response


def install_auth(app: FastAPI) -> None:
    @app.exception_handler(AuthError)
    async def _auth_error(_request: Request, error: AuthError):
        return JSONResponse({"detail": error.message, "code": error.code}, status_code=error.status_code)

    app.include_router(router)
