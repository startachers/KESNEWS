(function registerRestartGuard() {
  const button = document.getElementById("restartServerBtn");
  const status = document.getElementById("globalStatus");
  if (!button) return;

  const originalHtml = button.innerHTML;
  const updateStatus = message => {
    if (status) status.textContent = message;
  };
  const delay = milliseconds => new Promise(resolve => window.setTimeout(resolve, milliseconds));

  async function waitForRestart(previousProcessId) {
    const deadline = Date.now() + 45000;
    while (Date.now() < deadline) {
      await delay(500);
      try {
        const response = await fetch(`/api/health?restartCheck=${Date.now()}`, {
          cache: "no-store",
          headers: { Accept: "application/json" },
        });
        const body = await response.json();
        if (response.ok && body.service === "kesco-media-briefing"
          && !String(body.instanceId || "").startsWith(`${previousProcessId}-`)) return;
      } catch {
        // 서버가 내려갔다가 다시 뜨는 동안의 연결 오류는 정상적인 재시작 과정이다.
      }
    }
    throw new Error("새 서버 연결을 확인하지 못했습니다.");
  }

  button.addEventListener("click", async () => {
    if (button.dataset.restartHandler === "module" || button.disabled) return;
    button.disabled = true;
    button.textContent = "재시작 중…";
    updateStatus("로컬 서버를 재시작하고 있습니다…");
    try {
      const currentResponse = await fetch(`/api/health?beforeRestart=${Date.now()}`, {
        cache: "no-store", headers: { Accept: "application/json" },
      });
      const current = await currentResponse.json();
      let previousProcessId = String(current.instanceId || "").split("-", 1)[0];
      try {
        const response = await fetch("/api/operations/restart", {
          method: "POST",
          cache: "no-store",
          headers: { Accept: "application/json", "X-KESCO-Restart": "confirmed" },
        });
        const body = await response.json();
        if (!response.ok || !body.ok) throw new Error(body?.error?.message || "재시작 요청 실패");
        previousProcessId = String(body.data.processId || previousProcessId);
      } catch (error) {
        console.info("재시작 POST 연결이 종료되어 새 인스턴스를 직접 확인합니다.", error);
      }
      if (!previousProcessId) throw new Error("기존 서버 인스턴스를 확인하지 못했습니다.");
      await waitForRestart(previousProcessId);
      const url = new URL(window.location.href);
      url.searchParams.set("v", String(Date.now()));
      window.location.replace(url.toString());
    } catch (error) {
      button.disabled = false;
      button.innerHTML = originalHtml;
      updateStatus(`서버 재시작 실패 · ${error.message}`);
    }
  });
}());
