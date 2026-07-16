from __future__ import annotations

import os
import re
from pathlib import Path

_ENV_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def load_env(path: Path) -> int:
    """의존성 없이 단순 KEY=value 파일을 읽되 이미 설정된 환경변수는 보존한다."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return 0

    loaded = 0
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _ENV_LINE.fullmatch(line)
        if not match:
            continue
        key, value = match.groups()
        if key in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value
        loaded += 1
    return loaded
