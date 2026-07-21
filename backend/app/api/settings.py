from __future__ import annotations

from fastapi import APIRouter

from backend.app.api.envelope import ok_envelope
from backend.app.services.settings import (
    CollectionSettings,
    get_effective_settings,
    reset_settings,
    save_settings,
)

router = APIRouter()


def _response(settings: CollectionSettings, meta: dict) -> dict:
    return ok_envelope(settings.model_dump(), meta)


@router.get("/api/settings")
def get_settings() -> dict:
    settings, meta = get_effective_settings()
    return _response(settings, meta)


@router.put("/api/settings")
def put_settings(request: CollectionSettings) -> dict:
    settings, meta = save_settings(request)
    return _response(settings, meta)


@router.post("/api/settings/reset")
def post_settings_reset() -> dict:
    settings, meta = reset_settings()
    return _response(settings, meta)
