"""Temporary, existing-admin-only metadata inspection for the private deployment DB."""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from app.auth.deps import require_user
from app.auth.service import SessionInfo
from app.db_metadata import inspect_environment

router = APIRouter(prefix="/api/v1/admin", include_in_schema=False)


@router.get("/db-inspection")
def db_inspection(session: SessionInfo = Depends(require_user)) -> JSONResponse:
    if session.user.role != "admin":
        raise HTTPException(status_code=403, detail="이 진단을 실행할 권한이 없습니다.")
    return JSONResponse(
        inspect_environment(os.environ),
        headers={"Cache-Control": "no-store, private", "Vary": "Cookie"},
    )
