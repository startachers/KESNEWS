from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = BASE_DIR / "frontend"
LOG_DIR = BASE_DIR / "logs"
OLLAMA_TAGS_URL = "http://127.0.0.1:11434/api/tags"

LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "app.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("kesco.app")

app = FastAPI(title="KESCO Media Briefing")


def _fetch_ollama_tags() -> tuple[list[dict], str]:
    """Ollama는 선택 의존성이다. 실패해도 /api/health 자체는 정상으로 응답한다."""
    try:
        request = urllib.request.Request(OLLAMA_TAGS_URL, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=1.5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        logger.info("Ollama 조회 실패, models=[]로 응답: %s", exc)
        return [], ""

    models = payload.get("models", [])
    default_model = models[0].get("name", "") if models else ""
    return models, default_model


@app.get("/api/health")
async def health() -> dict:
    models, default_model = await asyncio.to_thread(_fetch_ollama_tags)
    return {"ok": True, "models": models, "defaultModel": default_model, "error": None}


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
