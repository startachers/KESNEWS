from __future__ import annotations

import http.client
import json
import os
import socket
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from backend.app.services.ai.runtime import AnalysisCancelled, CancellationToken


class OllamaError(Exception):
    pass


DEFAULT_CONTEXT_LENGTH = 65_536
DEFAULT_31B_CONTEXT_LENGTH = 65_536
DEFAULT_MAX_OUTPUT_TOKENS = 2_048


def configured_context_length() -> int:
    raw = os.environ.get("KESCO_OLLAMA_NUM_CTX")
    if raw is None:
        return DEFAULT_CONTEXT_LENGTH
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError("KESCO_OLLAMA_NUM_CTX는 정수여야 합니다.") from exc
    if value < 4_096:
        raise RuntimeError("KESCO_OLLAMA_NUM_CTX는 4096 이상이어야 합니다.")
    return value


class OllamaClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        timeout: float = 1_200.0,
        context_length: int = DEFAULT_CONTEXT_LENGTH,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.context_length = context_length
        self.max_output_tokens = max_output_tokens

    def context_length_for(self, model: str) -> int:
        if ":31b" not in model.lower():
            return self.context_length
        raw = os.environ.get("KESCO_OLLAMA_NUM_CTX_31B")
        if raw is None:
            return min(self.context_length, DEFAULT_31B_CONTEXT_LENGTH)
        try:
            value = int(raw)
        except ValueError as exc:
            raise OllamaError("KESCO_OLLAMA_NUM_CTX_31B는 정수여야 합니다.") from exc
        if value < 4_096:
            raise OllamaError("KESCO_OLLAMA_NUM_CTX_31B는 4096 이상이어야 합니다.")
        return min(self.context_length, value)

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

    def generate(
        self,
        *,
        model: str,
        prompt: str,
        format_schema: Mapping[str, Any] | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> str:
        token = cancel_token or CancellationToken()
        token.raise_if_cancelled()
        data = json.dumps(
            {
                "model": model,
                "prompt": prompt,
                "stream": True,
                "think": False,
                "format": dict(format_schema) if format_schema is not None else "json",
                "options": {
                    "num_ctx": self.context_length_for(model),
                    "num_predict": self.max_output_tokens,
                    "temperature": 0.1,
                },
            }
        ).encode("utf-8")
        parsed = urlsplit(self.base_url)
        if parsed.scheme != "http" or not parsed.hostname:
            raise OllamaError("Ollama 생성 API는 로컬 HTTP 주소만 지원합니다.")
        connection = http.client.HTTPConnection(
            parsed.hostname,
            parsed.port or 80,
            timeout=self.timeout,
        )

        def close_connection() -> None:
            sock = connection.sock
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            connection.close()

        parts: list[str] = []
        response = None
        token.attach_closer(close_connection)
        try:
            connection.request(
                "POST",
                f"{parsed.path.rstrip('/')}/api/generate",
                body=data,
                headers={
                    "Accept": "application/x-ndjson",
                    "Content-Type": "application/json",
                    "Connection": "close",
                },
            )
            response = connection.getresponse()
            if response.status >= 400:
                raise OllamaError(f"HTTP Error {response.status}: {response.reason}")
            for raw_line in response:
                token.raise_if_cancelled()
                if not raw_line.strip():
                    continue
                chunk = json.loads(raw_line.decode("utf-8"))
                if chunk.get("error"):
                    raise OllamaError(str(chunk["error"]))
                piece = chunk.get("response")
                if isinstance(piece, str):
                    parts.append(piece)
                if chunk.get("done"):
                    break
        except AnalysisCancelled:
            raise
        except (http.client.HTTPException, TimeoutError, ValueError, OSError) as exc:
            token.raise_if_cancelled()
            raise OllamaError(str(exc)) from exc
        finally:
            token.detach_closer()
            if response is not None:
                response.close()
            connection.close()
        token.raise_if_cancelled()
        result = "".join(parts)
        if not result:
            raise OllamaError("Ollama 응답에 response 문자열이 없습니다.")
        return result

    def unload_model(self, model: str) -> None:
        self._request("/api/generate", {"model": model, "keep_alive": 0}, timeout=15.0)


default_client = OllamaClient(context_length=configured_context_length())
