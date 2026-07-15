from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class OllamaError(Exception):
    pass


class OllamaClient:
    def __init__(self, base_url: str = "http://127.0.0.1:11434", timeout: float = 600.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(
        self, path: str, payload: dict[str, Any] | None = None, timeout: float | None = None
    ) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            method="POST" if data is not None else "GET",
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            raise OllamaError(str(exc)) from exc

    def list_models(self) -> list[dict[str, Any]]:
        payload = self._request("/api/tags", timeout=1.5)
        models = payload.get("models")
        return models if isinstance(models, list) else []

    def generate(self, *, model: str, prompt: str) -> str:
        payload = self._request(
            "/api/generate",
            {"model": model, "prompt": prompt, "stream": False, "format": "json"},
        )
        response = payload.get("response")
        if not isinstance(response, str):
            raise OllamaError("Ollama 응답에 response 문자열이 없습니다.")
        return response


default_client = OllamaClient()
