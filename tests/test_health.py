from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app import main as main_module
from backend.app.api import operations as operations_api

client = TestClient(app)


def test_health_returns_flat_ok_shape():
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["service"] == "kesco-media-briefing"
    assert body["instanceId"]
    assert isinstance(body["models"], list)
    assert isinstance(body["defaultModel"], str)
    assert body["error"] is None or isinstance(body["error"], str)
    assert body["dbConnected"] is True
    assert body["dbIntegrity"] is True


def test_health_prefers_installed_31b_as_default(monkeypatch):
    monkeypatch.setattr(
        main_module.default_client,
        "list_models",
        lambda: [{"name": "gemma4:26b"}, {"name": "gemma4:31b"}],
    )

    models, default_model, error = main_module._fetch_ollama_tags()

    assert [model["name"] for model in models] == ["gemma4:26b", "gemma4:31b"]
    assert default_model == "gemma4:31b"
    assert error is None


def test_index_html_is_served_at_root():
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert 'id="restartServerBtn"' in response.text
    assert response.text.index('id="restartServerBtn"') < response.text.index('id="refreshBtn"')
    assert 'id="governmentPressBtn"' in response.text
    assert response.text.index('id="governmentPressBtn"') < response.text.index('id="refreshBtn"')
    assert "js/restart-guard.js?v=20260720-1" in response.text
    assert "js/app.js?v=20260723-6" in response.text
    assert 'id="cancelFinalizeBtn" hidden>확정 취소</button>' in response.text
    assert 'id="finalizeBtn">최종 확정</button>' not in response.text
    assert 'id="reopenBtn"' not in response.text
    assert 'id="resetTodayBtn"' in response.text
    assert 'id="searchProgress"' in response.text
    assert 'role="progressbar"' in response.text
    assert "css/app.css?v=20260722-1" in response.text
    assert 'id="chatGptShortcutBtn" type="button"' in response.text
    assert 'id="claudeShortcutBtn" type="button"' in response.text
    assert 'id="autoSelectBtn" type="button" aria-busy="false"' in response.text
    assert response.text.index('value="gemma4:31b"') < response.text.index('value="gemma4:26b"')

    app_script = client.get("/js/app.js")
    assert 'dialogs.js?v=20260720-1' in app_script.text
    assert 'articles.js?v=20260723-1' in app_script.text
    assert 'collection.js?v=20260723-21' in app_script.text
    assert 'notifications.js?v=20260716-1' in app_script.text
    assert 'report-draft.js?v=20260722-3' in app_script.text
    assert 'openExternalAi("chatgpt")' in app_script.text
    assert 'openExternalAi("claude")' in app_script.text
    assert 'ai-analysis.js?v=20260722-1' in app_script.text
    assert 'auto-selection.js?v=20260721-1' in app_script.text
    assert 'dataset.restartHandler = "module"' in app_script.text
    assert 'runSearch(false, "government")' in app_script.text

    assert '$("resetTodayBtn").addEventListener("click", resetTodayWork)' in app_script.text

    store_script = client.get("/js/state/store.js")
    assert '["http:", "https:"].includes(location.protocol)' in store_script.text
    assert '? "/api"' in store_script.text

    restart_guard = client.get("/js/restart-guard.js")
    assert restart_guard.status_code == 200
    assert 'button.dataset.restartHandler === "module"' in restart_guard.text
    assert '"X-KESCO-Restart": "confirmed"' in restart_guard.text
    assert 'cache: "no-store"' in restart_guard.text
    assert "beforeRestart=" in restart_guard.text
    assert "새 인스턴스를 직접 확인합니다" in restart_guard.text

    assert '<option value="collection">관련기사 수집순</option>' in response.text

    dialogs_script = client.get("/js/ui/dialogs.js")
    assert 'import { setStatus, showToast } from "./notifications.js?v=20260716-1";' in dialogs_script.text
    assert 'articles.js?v=20260723-1' in dialogs_script.text
    assert "await api.getServerProcessId()" in dialogs_script.text

    client_script = client.get("/js/api/client.js")
    assert "export async function getServerProcessId()" in client_script.text
    assert "서버가 45초 안에 다시 시작되지 않았습니다" in client_script.text
    assert "export function searchRelatedArticles" in client_script.text

    articles_script = client.get("/js/features/articles.js")
    assert 'data-action="search-related"' in articles_script.text
    assert "관련기사 검색" in articles_script.text
    assert "여러 조합으로 Google·네이버" in articles_script.text
    assert "최대 10건" in articles_script.text
    assert 'data-action="edit-article-manual-body"' in articles_script.text
    assert 'data-action="save-article-manual-body"' in articles_script.text
    assert "article-manual-body-editor" in articles_script.text

    renderers_script = client.get("/js/ui/renderers.js")
    assert 'articles.js?v=20260723-1' in renderers_script.text

    auto_selection_script = client.get("/js/features/auto-selection.js")
    assert 'setAttribute("aria-busy", String(value))' in auto_selection_script.text
    assert "<b>기사 사실</b>" in auto_selection_script.text
    assert "<b>공사 연관성</b>" not in auto_selection_script.text
    assert "<b>선정 이유</b>" not in auto_selection_script.text
    assert "Top Issues는 수동으로 선택해 주세요" in auto_selection_script.text
    assert 'error?.name === "AbortError"' in auto_selection_script.text
    assert "await api.cancelBriefingAnalysis(reportDate)" in auto_selection_script.text
    assert "activatedTopIssueCount" not in auto_selection_script.text

    data_io_script = client.get("/js/features/data-io.js")
    assert "오늘 수집한 기사, 선정·메모·Top Issues" in data_io_script.text
    assert "await api.resetTodayWork(state.date, state.revision)" in data_io_script.text
    assert "export async function openPreview()" in data_io_script.text
    preview_function = data_io_script.text.split("export async function openPreview()", 1)[1]
    preview_function = preview_function.split("export function openFinalReport()", 1)[0]
    assert preview_function.index("await flushArticleChanges()") < preview_function.index(
        "previewWindow.location.replace(previewUrl)"
    )
    assert preview_function.index("await flushDailyState()") < preview_function.index(
        "previewWindow.location.replace(previewUrl)"
    )
    cancel_function = data_io_script.text.split(
        "export async function cancelFinalization()", 1
    )[1].split("export async function resetTodayWork()", 1)[0]
    assert "await api.getBriefingVersion(state.date, state.latestFinalVersion)" in cancel_function
    assert "await api.reopenBriefing(state.date, state.revision)" in cancel_function
    assert "restoreFinalPresentation(" in cancel_function
    assert "직전 작업본으로 돌아" in cancel_function
    assert "확정 기록은 보존" in cancel_function
    assert "export async function finalizeCurrentBriefing()" not in data_io_script.text
    restore_function = data_io_script.text.split(
        "function restoreFinalPresentation(date, revision, snapshot)", 1
    )[1].split("export function loadSample()", 1)[0]
    assert "article.reportSummary" in restore_function
    assert "articleOrder:" in restore_function
    assert "articleSummarySourceRevision:" in restore_function
    assert "localStorage.setItem(" in restore_function
    final_report_function = data_io_script.text.split(
        "export async function openFinalReport()", 1
    )[1].split("export async function cancelFinalization()", 1)[0]
    assert "await api.listBriefingVersions(state.date)" in final_report_function
    assert "item.version > current.version" in final_report_function
    assert "?version=${encodeURIComponent(latest.version)}" in final_report_function
    assert "reportWindow.location.replace(reportUrl)" in final_report_function

    store_script = client.get("/js/state/store.js")
    flush_function = store_script.text.split("export function flushDailyState()", 1)[1].split(
        "export let settings", 1
    )[0]
    assert "if (!saveTimer) return savePromise;" in flush_function

    report_draft_script = client.get("/js/features/report-draft.js")
    assert 'chatgpt: { label: "ChatGPT", url: "https://chatgpt.com/" }' in report_draft_script.text
    assert 'claude: { label: "Claude", url: "https://claude.ai/new" }' in report_draft_script.text
    assert "export const EXTERNAL_ANALYSIS_PROMPT" in report_draft_script.text
    assert "첨부한 「KESCO CEO 일일 언론브리핑 AI 분석자료」 Markdown 파일만을 근거" in (
        report_draft_script.text
    )
    assert "전체 문장의 약 30%만 사실 설명에 사용" in report_draft_script.text
    assert "최대 2개 문단으로 작성하십시오." in report_draft_script.text
    assert "전체 분량은 공백 포함 약 1,000~1,400자" in report_draft_script.text
    assert "최대 1,600자를 넘지 마십시오." in report_draft_script.text
    assert "④ 기타 동향" in report_draft_script.text
    assert "④ 참고 동향" not in report_draft_script.text
    assert "기사 ID, 이슈 ID, URL, 분석 적합도와 내부 분류값을 출력하지 마십시오." in (
        report_draft_script.text
    )
    assert 'window.open("about:blank", "_blank")' in report_draft_script.text
    assert "navigator.clipboard.writeText(EXTERNAL_ANALYSIS_PROMPT)" in report_draft_script.text
    assert 'document.execCommand("copy")' in report_draft_script.text
    shortcut_function = report_draft_script.text.split(
        "export async function openExternalAi", 1
    )[1].split("function emptyContent", 1)[0]
    assert "getAnalysisMarkdown" not in shortcut_function

    api_client = client.get("/js/api/client.js")
    assert "finalizeBriefing(date, expectedRevision, presentation = {})" in api_client.text
    assert "JSON.stringify({ expectedRevision, ...presentation })" in api_client.text
    assert "getBriefingVersion(date, version)" in api_client.text
    assert 'confirmation: "RESET_TODAY"' in api_client.text
    assert "const MANAGEMENT_ANALYSIS_REQUEST_TIMEOUT_MS = 1230000;" in api_client.text
    assert "const ARTICLE_SELECTION_REQUEST_TIMEOUT_MS = 660000;" in api_client.text
    analyze_request = api_client.text.split("export function analyzeBriefing", 1)[1]
    analyze_request = analyze_request.split("export function cancelBriefingAnalysis", 1)[0]
    assert "}, MANAGEMENT_ANALYSIS_REQUEST_TIMEOUT_MS);" in analyze_request
    selection_request = api_client.text.split("export function recommendBriefingArticles", 1)[1]
    selection_request = selection_request.split(
        "export function applyBriefingArticleRecommendations", 1
    )[0]
    assert "}, ARTICLE_SELECTION_REQUEST_TIMEOUT_MS);" in selection_request

    stylesheet = client.get("/css/app.css")
    assert "button:disabled { cursor: not-allowed;" in stylesheet.text
    assert 'button[aria-busy="true"] { cursor: progress;' in stylesheet.text
    assert ".side-card #resetTodayBtn" in stylesheet.text


def test_frontend_assets_disable_browser_cache():
    for path in ("/", "/js/app.js", "/css/app.css"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store, max-age=0"
        assert response.headers["pragma"] == "no-cache"


def test_restart_requires_confirmation_header(monkeypatch):
    scheduled = []
    monkeypatch.setattr(operations_api, "schedule_server_restart", scheduled.append)

    response = client.post("/api/operations/restart")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "SYSTEM_RESTART_FORBIDDEN"
    assert scheduled == []


def test_restart_schedules_helper_after_confirmed_request(monkeypatch):
    scheduled = []
    monkeypatch.setattr(operations_api, "schedule_server_restart", scheduled.append)

    response = client.post(
        "/api/operations/restart", headers={"X-KESCO-Restart": "confirmed"}
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "restarting"
    assert scheduled == [response.json()["data"]["processId"]]
