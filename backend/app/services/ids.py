from __future__ import annotations

import secrets
import time


def make_id() -> str:
    """frontend/js/utils/strings.js uid()와 형식은 다르지만 동일하게 불투명한 고유 문자열이다."""
    return f"a-{int(time.time() * 1000):x}-{secrets.token_hex(4)}"
