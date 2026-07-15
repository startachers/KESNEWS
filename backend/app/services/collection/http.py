from __future__ import annotations

import urllib.error
import urllib.request


class CollectionHttpError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def http_get(url: str, headers: dict[str, str], timeout_seconds: float) -> tuple[int, str]:
    """동기 urllib 호출. backend/app/main.py의 Ollama 조회와 동일 패턴이며,
    provider별 동시 실행은 호출부에서 asyncio.to_thread로 감싼다(신규 런타임 의존성 회피)."""
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 (고정 provider URL만 사용)
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return exc.code, body
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise CollectionHttpError("연결 시간이 초과됐거나 서버에서 데이터 제공 경로에 연결할 수 없습니다.") from exc
