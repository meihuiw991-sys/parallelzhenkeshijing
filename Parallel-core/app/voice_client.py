import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import websockets

from app.config import Settings

AudioHandler = Callable[[str], Awaitable[None]]


class VoiceProtocolError(RuntimeError):
    pass


class VoiceClient:
    def __init__(
        self,
        settings: Settings,
        on_audio: AudioHandler,
        logger: logging.LoggerAdapter,
    ) -> None:
        self.settings = settings
        self.on_audio = on_audio
        self.logger = logger
        self._audio_chunk_count = 0

    def session_update(self) -> dict[str, Any]:
        return {
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "voice": self.settings.voice_name,
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "output_sample_rate": self.settings.voice_output_sample_rate,
                "voice_cfg": {},
            },
        }

    @staticmethod
    def answer_item(text: str) -> dict[str, Any]:
        return {
            "type": "conversation.item.create",
            "item": {
                "type": "tts_text",
                "content": [{"type": "text", "text": text}],
            },
        }

    async def synthesize(self, text: str) -> None:
        if not text.strip():
            return
        self._audio_chunk_count = 0
        headers = {"Authorization": f"Bearer {self.settings.assistant_api_key}"}
        self.logger.info(
            "connecting to Voice url=%s text_length=%s sample_rate=%s",
            self.settings.voice_ws_url,
            len(text),
            self.settings.voice_output_sample_rate,
        )
        async with asyncio.timeout(self.settings.voice_timeout_seconds):
            async with websockets.connect(
                self.settings.voice_ws_url,
                subprotocols=["realtime"],
                additional_headers=headers,
                max_size=None,
                open_timeout=20,
                ping_interval=20,
                ping_timeout=20,
            ) as websocket:
                await websocket.send(json.dumps(self.session_update(), ensure_ascii=False))
                text_sent = False
                async for raw_message in websocket:
                    if not isinstance(raw_message, str):
                        continue
                    event = json.loads(raw_message)
                    event_type = event.get("type")
                    if event_type != "response.output_audio.delta":
                        self.logger.info("Voice event type=%s", event_type)
                    if event_type in {"session.created", "session.updated"} and not text_sent:
                        await websocket.send(json.dumps(self.answer_item(text), ensure_ascii=False))
                        text_sent = True
                    elif event_type == "response.output_audio.delta":
                        audio = event.get("delta")
                        if isinstance(audio, str) and audio:
                            self._audio_chunk_count += 1
                            if self._audio_chunk_count == 1 or self._audio_chunk_count % 20 == 0:
                                self.logger.info(
                                    "Voice audio chunk received count=%s base64_length=%s",
                                    self._audio_chunk_count,
                                    len(audio),
                                )
                            await self.on_audio(audio)
                    elif event_type == "response.done":
                        self.logger.info(
                            "Voice synthesis completed text_length=%s audio_chunks=%s",
                            len(text),
                            self._audio_chunk_count,
                        )
                        return
                    elif event_type == "error":
                        raise VoiceProtocolError(str(event.get("error", event)))
                raise VoiceProtocolError("Voice WebSocket closed before response.done")
