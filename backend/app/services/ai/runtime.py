from __future__ import annotations

import threading
from collections.abc import Callable


class AnalysisCancelled(Exception):
    def __init__(self, reason: str = "user"):
        super().__init__(reason)
        self.reason = reason


class CancellationToken:
    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._closer: Callable[[], None] | None = None
        self.reason = "user"

    def cancel(self, reason: str = "user") -> None:
        with self._lock:
            self.reason = reason
            self._event.set()
            closer = self._closer
        if closer is not None:
            try:
                closer()
            except OSError:
                pass

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled():
            raise AnalysisCancelled(self.reason)

    def attach_closer(self, closer: Callable[[], None]) -> None:
        with self._lock:
            self._closer = closer
            cancelled = self._event.is_set()
        if cancelled:
            try:
                closer()
            except OSError:
                pass

    def detach_closer(self) -> None:
        with self._lock:
            self._closer = None


class AnalysisRegistry:
    """단일 Mac에서 Ollama 분석 하나만 실행되도록 관리한다."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: dict[str, tuple[str, CancellationToken]] = {}

    def register(self, run_id: str, briefing_id: str, token: CancellationToken) -> bool:
        with self._lock:
            if self._active:
                return False
            self._active[run_id] = (briefing_id, token)
            return True

    def unregister(self, run_id: str) -> None:
        with self._lock:
            self._active.pop(run_id, None)

    def cancel_for_briefing(self, briefing_id: str, reason: str = "user") -> str | None:
        with self._lock:
            match = next(
                ((run_id, token) for run_id, (current_id, token) in self._active.items() if current_id == briefing_id),
                None,
            )
        if match is None:
            return None
        run_id, token = match
        token.cancel(reason)
        return run_id

    def active_run_id(self) -> str | None:
        with self._lock:
            return next(iter(self._active), None)


analysis_registry = AnalysisRegistry()
