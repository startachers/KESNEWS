from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastapi.testclient import TestClient
from logging.handlers import RotatingFileHandler

from backend.app.api import collections as collections_api
from backend.app.main import app
from backend.app.services.reports import storage

client = TestClient(app)


def test_operational_logs_use_size_based_rotation():
    handlers = [
        handler
        for handler in logging.getLogger().handlers
        if isinstance(handler, RotatingFileHandler) and getattr(handler, "_kesco_handler", False)
    ]
    assert {Path(handler.baseFilename).name for handler in handlers} == {
        "app.log",
        "collection.log",
        "ai.log",
    }
    assert all(handler.maxBytes == 5 * 1024 * 1024 for handler in handlers)
    assert all(handler.backupCount == 5 for handler in handlers)


def test_overlapping_collection_is_rejected(monkeypatch):
    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()

        async def fake_collection(payload):  # noqa: ARG001
            started.set()
            await release.wait()
            return {"status": "success"}

        monkeypatch.setattr(collections_api, "run_collection", fake_collection)
        request = collections_api.CollectionRequest(enableYonhap=True)
        first = asyncio.create_task(collections_api.create_collection(request))
        await started.wait()
        second = await collections_api.create_collection(request)
        release.set()
        await first
        return second

    response = asyncio.run(scenario())
    assert response.status_code == 409
    assert json.loads(response.body)["error"]["code"] == "COLLECTION_ALREADY_RUNNING"


def test_operations_status_reports_integrity_backup_and_collection_state():
    response = client.get("/api/operations/status")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["database"]["integrityOk"] is True
    assert data["backups"]["count"] >= 0
    assert "latest" in data["collection"]
    assert "lastSuccessful" in data["collection"]


def test_finalize_writes_immutable_snapshot_json_backup():
    report_date = "2026-09-09"
    briefing = client.put(
        f"/api/briefings/{report_date}",
        json={"expectedRevision": 0, "preparedBy": "운영 테스트"},
    ).json()["data"]

    response = client.post(
        f"/api/briefings/{report_date}/finalize",
        json={"expectedRevision": briefing["revision"]},
    )

    assert response.status_code == 200
    path = storage.BRIEFING_BACKUPS_DIR / f"{report_date}_v1.json"
    assert path.is_file()
    backup = json.loads(path.read_text(encoding="utf-8"))
    assert backup["schemaVersion"] == 8
    assert backup["reportDate"] == report_date
    assert backup["briefingVersions"][0]["version"] == 1
    assert backup["briefingVersions"][0]["snapshot"]["reportDate"] == report_date
    assert Path(response.json()["data"]["reportHtmlPath"]).is_file()
