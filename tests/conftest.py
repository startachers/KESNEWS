"""테스트는 실제 운영 DB(data/kesco_media_briefing.db)를 절대 건드리지 않는다.

이 모듈은 pytest가 테스트 모듈을 import하기 전에 로드되므로, 여기서 환경변수를
설정해 `backend.app.repositories.database`가 처음 import될 때부터 임시 DB 경로를
쓰게 만든다.
"""

import os
import shutil
import tempfile

_TEST_DB_DIR = tempfile.mkdtemp(prefix="kesco-test-db-")
os.environ["KESCO_DB_PATH"] = os.path.join(_TEST_DB_DIR, "test.db")


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    shutil.rmtree(_TEST_DB_DIR, ignore_errors=True)
