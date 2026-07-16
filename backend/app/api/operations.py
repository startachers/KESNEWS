from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Header

from backend.app.api.envelope import error_response, ok_envelope
from backend.app.repositories import run_repository as run_repo
from backend.app.repositories.database import DB_PATH, check_database_integrity, get_connection
from backend.app.services.maintenance.backup import list_valid_backups
from backend.app.services.maintenance.restart import schedule_server_restart

router = APIRouter()
logger = logging.getLogger("kesco.operations")


@router.get("/api/operations/status")
async def operations_status() -> dict[str, Any]:
    integrity_ok, integrity_detail = check_database_integrity()
    connection = get_connection()
    try:
        latest = run_repo.get_latest_run_any_date(connection)
        latest_success = run_repo.get_latest_successful_run(connection)
    finally:
        connection.close()
    backups = list_valid_backups()
    return ok_envelope(
        {
            "database": {
                "path": str(DB_PATH),
                "integrityOk": integrity_ok,
                "integrity": integrity_detail,
            },
            "backups": {
                "count": len(backups),
                "latest": backups[0] if backups else None,
            },
            "collection": {
                "latest": run_repo.serialize_status(latest),
                "lastSuccessful": run_repo.serialize_status(latest_success),
            },
        }
    )


@router.post("/api/operations/restart")
async def restart_server(x_kesco_restart: str | None = Header(default=None)) -> dict[str, Any]:
    if x_kesco_restart != "confirmed":
        return error_response(
            "SYSTEM_RESTART_FORBIDDEN", "브라우저의 명시적인 재시작 확인이 필요합니다."
        )
    try:
        schedule_server_restart(os.getpid())
    except OSError:
        logger.exception("서버 재시작 도우미 실행 실패")
        return error_response("SYSTEM_RESTART_FAILED", "서버 재시작을 예약하지 못했습니다.")
    return ok_envelope({"status": "restarting", "processId": os.getpid()})
