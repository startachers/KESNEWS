from __future__ import annotations

import asyncio
from typing import Any

from backend.app.repositories import press_release_repository as press_release_repo
from backend.app.repositories.database import get_connection
from backend.app.services.collection.kesco_press import fetch_kesco_press

_refresh_lock = asyncio.Lock()


def get_kesco_press_cache_status() -> dict[str, Any]:
    connection = get_connection()
    try:
        return press_release_repo.cache_status(connection)
    finally:
        connection.close()


def _refresh_kesco_press_cache(max_records: int) -> dict[str, Any]:
    result = fetch_kesco_press(max_records)
    releases = result.get("pressReleases") or []
    connection = get_connection()
    try:
        with connection:
            for release in releases:
                press_release_repo.upsert_release(connection, release)
            status = press_release_repo.cache_status(connection)
    finally:
        connection.close()
    return {
        **status,
        "refreshedCount": len(releases),
        "warning": result.get("warning"),
    }


async def refresh_kesco_press_cache(max_records: int = 30) -> dict[str, Any]:
    async with _refresh_lock:
        return await asyncio.to_thread(_refresh_kesco_press_cache, max_records)
