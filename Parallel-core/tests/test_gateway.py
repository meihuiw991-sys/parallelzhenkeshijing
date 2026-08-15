from fastapi.testclient import TestClient

from app.main import app
from app.assistant_session import AssistantSession
from app.session import RenderSession


async def fake_start(self: RenderSession, message) -> None:
    self.state = "running"
    await self.send_json(
        {
            "type": "virtual_tryon_stream",
            "data": {
                "ok": True,
                "session_id": self.session_id,
                "rv2v_session_id": self.rv2v_session_id,
                "state": "running",
                "playback_url": None,
                "transport": "websocket_jpeg",
                "width": 1248,
                "height": 720,
                "fps": 24,
            },
        }
    )


def test_video_edit_config_reads_local_prompt() -> None:
    with TestClient(app) as client:
        response = client.get("/api/config/video-edit")

    assert response.status_code == 200
    assert response.json()["prompt"].strip()


def test_capabilities_reserve_voice_integration() -> None:
    with TestClient(app) as client:
        response = client.get("/api/capabilities")

    assert response.status_code == 200
    assert response.json() == {
        "video_edit": {"enabled": True},
        "voice_understanding": {"enabled": True},
        "visual_interaction": {"enabled": True},
    }


def test_assistant_websocket_accepts_messages(monkeypatch) -> None:
    async def fake_start(self: AssistantSession) -> None:
        await self.send_json({"type": "assistant_status", "state": "ready"})

    async def fake_stop(self: AssistantSession) -> None:
        return None

    monkeypatch.setattr(AssistantSession, "start", fake_start)
    monkeypatch.setattr(AssistantSession, "stop", fake_stop)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/assistant/test-assistant") as websocket:
            assert websocket.receive_json() == {"type": "assistant_status", "state": "ready"}
            websocket.send_json({"type": "ping", "t": 123})
            assert websocket.receive_json() == {"type": "pong", "t": 123}
            websocket.send_json({"type": "audio_chunk", "audio": "AAAA"})
            assert websocket.receive_json() == {"type": "audio_input_ready"}


def test_websocket_rejects_frame_without_metadata() -> None:
    with TestClient(app) as client:
        with client.websocket_connect("/ws/render/test-no-meta") as websocket:
            assert websocket.receive_json()["event"] == "connected"
            websocket.send_bytes(b"\xff\xd8test")
            error = websocket.receive_json()
            assert error["error_code"] == "INVALID_MESSAGE"


def test_websocket_start_and_accept_jpeg(monkeypatch) -> None:
    monkeypatch.setattr(RenderSession, "start", fake_start)
    with TestClient(app) as client:
        with client.websocket_connect("/ws/render/test-start") as websocket:
            assert websocket.receive_json()["event"] == "connected"
            websocket.send_json(
                {
                    "type": "start_stream_edit",
                    "prompt": "watercolor",
                    "options": {"output_quality": 85},
                }
            )
            started = websocket.receive_json()
            assert started["type"] == "virtual_tryon_stream"
            assert started["data"]["transport"] == "websocket_jpeg"

            websocket.send_json(
                {
                    "type": "input_frame",
                    "seq": 1,
                    "t_capture_ms": 1000,
                    "mime_type": "image/jpeg",
                }
            )
            websocket.send_bytes(b"\xff\xd8test")


def test_websocket_rejects_missing_prompt() -> None:
    with TestClient(app) as client:
        with client.websocket_connect("/ws/render/test-prompt") as websocket:
            websocket.receive_json()
            websocket.send_json({"type": "start_stream_edit", "prompt": ""})
            error = websocket.receive_json()
            assert error["error_code"] == "INVALID_MESSAGE"
