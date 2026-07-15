from backend.app.services.ai.ollama_client import OllamaClient


def test_generate_sends_configured_64k_context(monkeypatch):
    client = OllamaClient(context_length=65_536)
    captured = {}

    def fake_request(path, payload=None, timeout=None):  # noqa: ARG001
        captured["path"] = path
        captured["payload"] = payload
        return {"response": "{}"}

    monkeypatch.setattr(client, "_request", fake_request)
    assert client.generate(model="gemma4:26b", prompt="test") == "{}"
    assert captured["path"] == "/api/generate"
    assert captured["payload"]["options"] == {"num_ctx": 65_536}
