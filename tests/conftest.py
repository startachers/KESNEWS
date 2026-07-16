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
os.environ["KESCO_BACKUPS_DIR"] = os.path.join(_TEST_DB_DIR, "backups")
os.environ["KESCO_REPORTS_DIR"] = os.path.join(_TEST_DB_DIR, "reports")
os.environ["KESCO_BRIEFING_BACKUPS_DIR"] = os.path.join(_TEST_DB_DIR, "briefing-backups")
os.environ.pop("NAVER_CLIENT_ID", None)
os.environ.pop("NAVER_CLIENT_SECRET", None)

# `TestClient(app)`를 `with` 없이 쓰는 기존 테스트들은 FastAPI startup 이벤트를 트리거하지
# 않으므로, 여기서 미리 migration을 적용해 API 테스트가 실제 서버 기동 여부와 무관하게
# 항상 스키마가 준비된 상태에서 실행되도록 한다.
from backend.app.repositories.database import init_db  # noqa: E402

init_db()


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    shutil.rmtree(_TEST_DB_DIR, ignore_errors=True)
