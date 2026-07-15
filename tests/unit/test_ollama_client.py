import json
import threading

from backend.app.services.ai.ollama_client import OllamaClient
from backend.app.services.ai.runtime import AnalysisCancelled, CancellationToken


class FakeResponse:
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False

    def __iter__(self):
        return iter(self.chunks)

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, response, captured):
        self.response = response
        self.captured = captured
        self.sock = None

    def request(self, method, path, body, headers):
        self.captured.update({"method": method, "path": path, "payload": json.loads(body), "headers": headers})

    def getresponse(self):
        self.response.status = 200
        return self.response

    def close(self):
        pass


def test_generate_sends_structured_bounded_request(monkeypatch):
    client = OllamaClient(context_length=65_536)
    captured = {}

    def fake_connection(host, port, timeout):
        captured.update({"host": host, "port": port, "timeout": timeout})
        return FakeConnection(FakeResponse([b'{"response":"{}","done":true}\n']), captured)

    monkeypatch.setattr("backend.app.services.ai.ollama_client.http.client.HTTPConnection", fake_connection)
    schema = {"type": "object"}
    assert client.generate(model="gemma4:26b", prompt="test", format_schema=schema) == "{}"
    assert captured["payload"]["stream"] is True
    assert captured["payload"]["think"] is False
    assert captured["payload"]["format"] == schema
    assert captured["payload"]["options"] == {
        "num_ctx": 65_536,
        "num_predict": 2_048,
        "temperature": 0.1,
    }


def test_31b_uses_safe_16k_context(monkeypatch):
    client = OllamaClient(context_length=65_536)
    captured = {}

    def fake_connection(host, port, timeout):  # noqa: ARG001
        return FakeConnection(FakeResponse([b'{"response":"{}","done":true}\n']), captured)

    monkeypatch.setattr("backend.app.services.ai.ollama_client.http.client.HTTPConnection", fake_connection)
    client.generate(model="gemma4:31b", prompt="test")
    assert captured["payload"]["options"]["num_ctx"] == 16_384


def test_cancel_interrupts_connection_before_first_response(monkeypatch):
    started = threading.Event()
    closed = threading.Event()
    token = CancellationToken()
    outcome = {}

    class BlockingSocket:
        def shutdown(self, how):  # noqa: ARG002
            closed.set()

    class BlockingConnection:
        def __init__(self, host, port, timeout):  # noqa: ARG002
            self.sock = BlockingSocket()

        def request(self, method, path, body, headers):  # noqa: ARG002
            started.set()

        def getresponse(self):
            closed.wait(timeout=2)
            raise OSError("closed")

        def close(self):
            closed.set()

    monkeypatch.setattr(
        "backend.app.services.ai.ollama_client.http.client.HTTPConnection", BlockingConnection
    )

    def run_generate():
        try:
            OllamaClient().generate(model="gemma4:31b", prompt="test", cancel_token=token)
        except Exception as exc:  # noqa: BLE001
            outcome["error"] = exc

    thread = threading.Thread(target=run_generate)
    thread.start()
    assert started.wait(timeout=1)
    token.cancel()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert isinstance(outcome["error"], AnalysisCancelled)
