import logging
import asyncio

from app.config import Settings
from app.talker_client import TalkerClient


async def ignore_event(event) -> None:
    return None


async def ignore_tool(name, arguments) -> str:
    return "ok"


def make_settings() -> Settings:
    return Settings(
        model_ws_url="wss://example.test/ws",
        model_health_url="https://example.test/health",
        model_api_key="secret",
    )


def test_talker_session_uses_audio_and_server_vad() -> None:
    client = TalkerClient(
        make_settings(),
        ignore_event,
        ignore_tool,
        logging.LoggerAdapter(logging.getLogger(__name__), {}),
    )

    payload = client._session_update()

    assert payload["type"] == "session.update"
    assert payload["session"]["modalities"] == ["text", "audio"]
    assert payload["session"]["turn_detection"] == {"type": "server_vad"}
    assert payload["session"]["sample_rate"] == 16000
    assert payload["session"]["output_sample_rate"] == 24000


def test_talker_registers_visual_tool() -> None:
    payload = TalkerClient._tools_payload()

    assert payload["type"] == "set_tools"
    assert payload["tools"][0]["name"] == "describe_current_view"
    assert payload["tools"][0]["parameters"]["required"] == ["question"]


def test_assistant_key_prefers_second_model_key() -> None:
    settings = make_settings().model_copy(update={"model_api_key_2": "assistant-secret"})

    assert settings.assistant_api_key == "assistant-secret"


def test_assistant_key_falls_back_to_model_key() -> None:
    assert make_settings().assistant_api_key == "secret"


def test_tools_register_after_session_updated() -> None:
    sent = []
    events = []

    class FakeWebSocket:
        async def send(self, message) -> None:
            sent.append(message)

    async def capture_event(event) -> None:
        events.append(event)

    client = TalkerClient(
        make_settings(),
        capture_event,
        ignore_tool,
        logging.LoggerAdapter(logging.getLogger(__name__), {}),
    )

    async def scenario() -> None:
        websocket = FakeWebSocket()
        await client._handle_event(websocket, {"type": "session.created"})
        assert sent == []
        await client._handle_event(websocket, {"type": "session.updated"})
        assert len(sent) == 1
        assert events == [{"type": "assistant_status", "state": "ready"}]
        if client._created_fallback_task is not None:
            client._created_fallback_task.cancel()
            await asyncio.gather(client._created_fallback_task, return_exceptions=True)

    asyncio.run(scenario())
