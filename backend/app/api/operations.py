from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from backend.app.api.envelope import ok_envelope
from backend.app.repositories import run_repository as run_repo
from backend.app.repositories.database import DB_PATH, check_database_integrity, get_connection
from backend.app.services.maintenance.backup import list_valid_backups

router = APIRouter()


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
