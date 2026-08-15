import asyncio
import base64
import logging
from collections import deque
from typing import Any

import websockets
from fastapi import WebSocket

from app.config import Settings
from app.demo_mocks import interaction_mock, talker_mock
from app.interaction_client import InteractionClient, InteractionError, InteractionSilence
from app.talker_client import TalkerClient, TalkerProtocolError
from app.visual_router import VisualIntentRouter
from app.voice_client import VoiceClient, VoiceProtocolError


class SessionLoggerAdapter(logging.LoggerAdapter):
    def process(self, message, kwargs):
        return f"[assistant:{self.extra['session_id']}] {message}", kwargs


class AssistantSession:
    def __init__(self, session_id: str, websocket: WebSocket, settings: Settings) -> None:
        self.session_id = session_id
        self.websocket = websocket
        self.settings = settings
        self.frames: deque[bytes] = deque(maxlen=3)
        self.interaction = InteractionClient(settings)
        self.logger = SessionLoggerAdapter(logging.getLogger(__name__), {"session_id": session_id})
        self.talker = TalkerClient(settings, self._on_talker_event, self._on_tool_call, self.logger)
        self.voice = VoiceClient(settings, self._on_voice_audio, self.logger)
        self.visual_router = VisualIntentRouter()
        self.talker_task: asyncio.Task[None] | None = None
        self._send_lock = asyncio.Lock()
        self._stopped = False
        self._audio_input_confirmed = False
        self._audio_chunk_count = 0
        self._vision_frame_count = 0
        self._visual_route_task: asyncio.Task[None] | None = None
        self._visual_result_future: asyncio.Future[str] | None = None
        self._suppress_automatic_response = False
        self._automatic_response_started = asyncio.Event()
        self._last_visual_result: str | None = None

    async def start(self) -> None:
        if self.talker_task is not None:
            return
        await self.send_json({"type": "assistant_status", "state": "connecting"})
        self.logger.info("assistant session starting")
        self.talker_task = asyncio.create_task(self._run_talker(), name=f"talker-{self.session_id}")

    async def accept_message(self, payload: dict[str, Any]) -> None:
        message_type = payload.get("type")
        if message_type == "audio_chunk":
            audio = payload.get("audio")
            if isinstance(audio, str) and 0 < len(audio) <= 20_000:
                await self.talker.append_audio(audio)
                self._audio_chunk_count += 1
                if self._audio_chunk_count == 1 or self._audio_chunk_count % 50 == 0:
                    self.logger.info(
                        "audio chunk accepted count=%s base64_length=%s",
                        self._audio_chunk_count,
                        len(audio),
                    )
                if not self._audio_input_confirmed:
                    self._audio_input_confirmed = True
                    await self.send_json({"type": "audio_input_ready"})
        elif message_type == "vision_frame":
            self._accept_vision_frame(payload.get("image"))
        elif message_type == "ping":
            await self.send_json({"type": "pong", "t": payload.get("t")})

    async def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        await self.talker.stop()
        if self.talker_task is not None:
            self.talker_task.cancel()
            await asyncio.gather(self.talker_task, return_exceptions=True)
        if self._visual_route_task is not None:
            self._visual_route_task.cancel()
            await asyncio.gather(self._visual_route_task, return_exceptions=True)

    def _accept_vision_frame(self, encoded: Any) -> None:
        if not isinstance(encoded, str) or not encoded:
            return
        if len(encoded) > 2_000_000:
            return
        try:
            frame = base64.b64decode(encoded, validate=True)
        except ValueError:
            return
        if frame.startswith(b"\xff\xd8") and len(frame) <= 1_500_000:
            self.frames.append(frame)
            self._vision_frame_count += 1
            if self._vision_frame_count == 1 or self._vision_frame_count % 10 == 0:
                self.logger.info(
                    "vision frame accepted count=%s bytes=%s cached=%s",
                    self._vision_frame_count,
                    len(frame),
                    len(self.frames),
                )

    async def _on_tool_call(self, name: str, arguments: dict[str, Any]) -> str:
        if name != "describe_current_view":
            return "不支持的工具"
        question = str(arguments.get("question") or "请介绍当前画面")
        if self._visual_result_future is not None and not self._visual_result_future.done():
            self.logger.info("native function call reuses active deterministic visual route")
            return await asyncio.shield(self._visual_result_future)
        return await self._analyze_visual(question)

    async def _analyze_visual(self, question: str) -> str:
        self.logger.info("visual tool called question=%r cached_frames=%s", question, len(self.frames))
        await self.send_json({"type": "vision_analysis", "state": "loading", "question": question})
        mocked_result = interaction_mock(question)
        if mocked_result is not None:
            self.logger.info("Interaction demo mock matched question=%r", question)
            await self.send_json(
                {
                    "type": "vision_analysis",
                    "state": "completed",
                    "question": question,
                    "result": mocked_result,
                }
            )
            self._last_visual_result = mocked_result
            return mocked_result
        try:
            result = await self.interaction.analyze(self.session_id, question, list(self.frames))
        except InteractionSilence:
            self.logger.info("Interaction returned silence question=%r", question)
            await self.send_json({"type": "vision_analysis", "state": "skipped", "question": question})
            raise
        except InteractionError as exc:
            message = str(exc)
            self.logger.warning("visual analysis failed question=%r error=%s", question, message)
            await self.send_json(
                {"type": "vision_analysis", "state": "error", "question": question, "message": message}
            )
            return f"视觉分析暂时不可用：{message}"
        await self.send_json(
            {"type": "vision_analysis", "state": "completed", "question": question, "result": result}
        )
        self.logger.info("visual analysis completed question=%r result_length=%s", question, len(result))
        self._last_visual_result = result
        return result

    async def _run_deterministic_visual_route(self, question: str) -> None:
        loop = asyncio.get_running_loop()
        result_future = loop.create_future()
        self._visual_result_future = result_future
        self._last_visual_result = None
        interaction_silent = False
        try:
            result = await self._analyze_visual(question)
            if not result_future.done():
                result_future.set_result(result)
        except InteractionSilence:
            interaction_silent = True
            result = ""
            if not result_future.done():
                result_future.set_result(result)
        except Exception as exc:
            if not result_future.done():
                result_future.set_result(f"视觉分析暂时不可用：{exc}")
            result = result_future.result()

        try:
            await asyncio.wait_for(self._automatic_response_started.wait(), timeout=1.5)
        except TimeoutError:
            self.logger.warning("Talker automatic response did not start before visual result injection")
        else:
            await asyncio.sleep(0.1)

        self._suppress_automatic_response = False
        self._automatic_response_started.clear()
        if interaction_silent:
            await self.talker.respond_to_text(question)
            self.logger.info("Interaction silence rerouted to normal Talker response")
        elif self._last_visual_result is None:
            await self.send_json(
                {"type": "assistant_text_replace", "text": "视觉分析暂时不可用，请稍后再试。"}
            )
            await self.send_json({"type": "assistant_text_done"})
            self.logger.info("visual analysis error shown without Voice synthesis")
        else:
            await self.send_json({"type": "assistant_text_replace", "text": result})
            await self.send_json({"type": "assistant_text_done"})
            await self._synthesize_text(result)
            self.logger.info("deterministic visual result displayed and sent to Voice")

    async def _run_mock_talker_route(self, result: str) -> None:
        try:
            await asyncio.wait_for(self._automatic_response_started.wait(), timeout=1.5)
        except TimeoutError:
            self.logger.warning("Talker automatic response did not start before mock response")
        else:
            await asyncio.sleep(0.1)
        self._suppress_automatic_response = False
        self._automatic_response_started.clear()
        await self.send_json({"type": "assistant_text_replace", "text": result})
        await self.send_json({"type": "assistant_text_done"})
        await self._synthesize_text(result)
        self.logger.info("Talker demo mock displayed and sent to Voice")

    async def _synthesize_text(self, text: str) -> None:
        try:
            await self.voice.synthesize(text)
        except (OSError, TimeoutError, websockets.WebSocketException, VoiceProtocolError) as exc:
            detail = self._voice_error_detail(exc)
            self.logger.exception("Voice synthesis failed detail=%s", detail)
            await self.send_json(
                {
                    "type": "assistant_tts_error",
                    "message": f"文本结果已生成，但语音播报暂时不可用：{detail}",
                }
            )

    async def _on_voice_audio(self, audio: str) -> None:
        await self.send_json({"type": "assistant_audio_delta", "audio": audio})

    async def _on_talker_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        if event_type not in {"response.output_audio.delta", "response.audio.delta"}:
            self.logger.info("talker event type=%s", event_type)
        if event_type == "conversation.item.input_audio_transcription.delta":
            await self.send_json({"type": "user_transcript_delta", "delta": event.get("delta", "")})
        elif event_type == "conversation.item.input_audio_transcription.completed":
            transcript = str(event.get("transcript", ""))
            self.logger.info("user transcription completed transcript=%r", transcript)
            await self.send_json(
                {"type": "user_transcript_completed", "transcript": transcript}
            )
            mocked_talker_result = talker_mock(transcript)
            if mocked_talker_result is not None:
                self.logger.info("Talker demo mock matched transcript=%r", transcript)
                await self.send_json(
                    {"type": "assistant_route", "route": "talker", "reason": "demo_mock"}
                )
                if self._visual_route_task is not None and not self._visual_route_task.done():
                    self._visual_route_task.cancel()
                    await asyncio.gather(self._visual_route_task, return_exceptions=True)
                self._suppress_automatic_response = True
                self._automatic_response_started.clear()
                self._visual_route_task = asyncio.create_task(
                    self._run_mock_talker_route(mocked_talker_result),
                    name=f"talker-mock-{self.session_id}",
                )
                self._visual_route_task.add_done_callback(self._log_route_task_result)
                return
            decision = self.visual_router.decide(transcript, self._last_visual_result is not None)
            self.logger.info(
                "assistant route decision route=%s reason=%s transcript=%r",
                "interaction" if decision.use_interaction else "talker",
                decision.reason,
                transcript,
            )
            await self.send_json(
                {
                    "type": "assistant_route",
                    "route": "interaction" if decision.use_interaction else "talker",
                    "reason": decision.reason,
                }
            )
            if decision.use_interaction:
                if self._visual_route_task is not None and not self._visual_route_task.done():
                    self._visual_route_task.cancel()
                    await asyncio.gather(self._visual_route_task, return_exceptions=True)
                self._suppress_automatic_response = True
                self._automatic_response_started.clear()
                self._visual_route_task = asyncio.create_task(
                    self._run_deterministic_visual_route(transcript),
                    name=f"visual-route-{self.session_id}",
                )
                self._visual_route_task.add_done_callback(self._log_route_task_result)
        elif event_type == "response.created" and self._suppress_automatic_response:
            self.logger.info("suppressing Talker automatic response for visual turn")
            self._automatic_response_started.set()
            await self.talker.cancel_response()
        elif self._suppress_automatic_response and event_type.startswith("response."):
            self.logger.info("dropping automatic visual-turn event type=%s", event_type)
        elif event_type == "response.output_audio_transcript.delta":
            await self.send_json({"type": "assistant_text_delta", "delta": event.get("delta", "")})
        elif event_type == "response.output_audio_transcript.done":
            self.logger.info("assistant transcript completed")
            await self.send_json({"type": "assistant_text_done"})
        elif event_type in {"response.output_audio.delta", "response.audio.delta"}:
            audio = event.get("delta") or event.get("audio")
            if isinstance(audio, str):
                await self.send_json({"type": "assistant_audio_delta", "audio": audio})
        elif event_type == "input_audio_buffer.speech_started":
            self.logger.info("talker VAD speech started")
            await self.send_json({"type": "speech_started"})
        elif event_type == "input_audio_buffer.speech_stopped":
            self.logger.info("talker VAD speech stopped")
            await self.send_json({"type": "speech_stopped"})
        elif event_type == "response.done":
            await self.send_json({"type": "assistant_response_done"})
        elif event_type == "assistant_status":
            await self.send_json(event)
        elif event_type == "error":
            await self.send_json({"type": "assistant_error", "message": str(event.get("error", event))})

    async def _run_talker(self) -> None:
        try:
            await self.talker.run()
        except asyncio.CancelledError:
            raise
        except (OSError, TimeoutError, websockets.WebSocketException, TalkerProtocolError) as exc:
            self.logger.exception("talker connection failed")
            await self.send_json({"type": "assistant_error", "message": self._connection_error_detail(exc)})
        except Exception as exc:
            self.logger.exception("unexpected assistant failure")
            await self.send_json({"type": "assistant_error", "message": str(exc)})

    async def send_json(self, payload: dict[str, Any]) -> None:
        async with self._send_lock:
            await self.websocket.send_json(payload)

    def _log_route_task_result(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            self.logger.info("assistant route task cancelled name=%s", task.get_name())
            return
        error = task.exception()
        if error is not None:
            self.logger.error(
                "assistant route task failed name=%s error=%s",
                task.get_name(),
                error,
                exc_info=(type(error), error, error.__traceback__),
            )

    @staticmethod
    def _connection_error_detail(exc: Exception) -> str:
        response = getattr(exc, "response", None)
        if response is None:
            return str(exc)
        status = getattr(response, "status_code", "unknown")
        headers = getattr(response, "headers", {})
        safe_header_names = (
            "x-request-id",
            "x-bce-request-id",
            "x-jdcloud-request-id",
            "server",
            "date",
        )
        safe_headers = {
            name: headers.get(name)
            for name in safe_header_names
            if headers.get(name) is not None
        }
        return f"Talker WebSocket 握手失败 HTTP {status}; response_headers={safe_headers}"

    @staticmethod
    def _voice_error_detail(exc: Exception) -> str:
        response = getattr(exc, "response", None)
        if response is None:
            return str(exc) or exc.__class__.__name__
        status = getattr(response, "status_code", "unknown")
        headers = getattr(response, "headers", {})
        request_id = (
            headers.get("x-request-id")
            or headers.get("x-bce-request-id")
            or headers.get("x-jdcloud-request-id")
        )
        suffix = f"，request_id={request_id}" if request_id else ""
        return f"Voice WebSocket 握手失败 HTTP {status}{suffix}"
