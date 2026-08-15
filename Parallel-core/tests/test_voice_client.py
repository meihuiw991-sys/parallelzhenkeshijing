import asyncio
import json
import logging

from app.config import Settings
from app.voice_client import VoiceClient


def make_client() -> VoiceClient:
    settings = Settings(
        model_ws_url="wss://example.test/ws",
        model_health_url="https://example.test/health",
        model_api_key_2="voice-key",
    )

    async def on_audio(audio: str) -> None:
        return None

    return VoiceClient(settings, on_audio, logging.LoggerAdapter(logging.getLogger(__name__), {}))


def test_voice_session_update_matches_provider_protocol() -> None:
    assert make_client().session_update() == {
        "type": "session.update",
        "session": {
            "modalities": ["text", "audio"],
            "voice": "default",
            "input_audio_format": "pcm16",
            "output_audio_format": "pcm16",
            "output_sample_rate": 24000,
            "voice_cfg": {},
        },
    }


def test_voice_uses_tts_text() -> None:
    assert VoiceClient.answer_item("画面中有一位用户。") == {
        "type": "conversation.item.create",
        "item": {
            "type": "tts_text",
            "content": [{"type": "text", "text": "画面中有一位用户。"}],
        },
    }


def test_voice_forwards_audio_delta(monkeypatch) -> None:
    sent_messages: list[dict] = []
    received_audio: list[str] = []

    class FakeWebSocket:
        def __init__(self) -> None:
            self.events = iter(
                [
                    json.dumps({"type": "session.created"}),
                    json.dumps({"type": "response.output_audio.delta", "delta": "AQID"}),
                    json.dumps({"type": "response.done"}),
                ]
            )

        async def send(self, raw_message: str) -> None:
            sent_messages.append(json.loads(raw_message))

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self.events)
            except StopIteration as exc:
                raise StopAsyncIteration from exc

    class FakeConnection:
        async def __aenter__(self):
            return FakeWebSocket()

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    def fake_connect(*args, **kwargs):
        return FakeConnection()

    client = make_client()

    async def capture_audio(audio: str) -> None:
        received_audio.append(audio)

    client.on_audio = capture_audio
    monkeypatch.setattr("app.voice_client.websockets.connect", fake_connect)

    asyncio.run(client.synthesize("画面中有一位用户。"))

    assert sent_messages == [
        client.session_update(),
        client.answer_item("画面中有一位用户。"),
    ]
    assert received_audio == ["AQID"]
