import asyncio
import logging
import time
import uuid
from typing import Any

from fastapi import WebSocket

from app.config import Settings
from app.frame_buffer import InputFrame, LatestFrameBuffer
from app.model_client import JoyAIModelClient, ModelProtocolError
from app.schemas import StartMessage, error_message


class RenderSession:
    def __init__(self, session_id: str, websocket: WebSocket, settings: Settings) -> None:
        self.session_id = session_id
        self.websocket = websocket
        self.settings = settings
        self.rv2v_session_id = f"{session_id}-tryon-{uuid.uuid4().hex[:8]}"
        self.state = "idle"
        self.frames = LatestFrameBuffer()
        self.pending_frame_meta: dict[str, Any] | None = None
        self.capture_times: dict[int, int] = {}
        self.model_task: asyncio.Task[None] | None = None
        self._send_lock = asyncio.Lock()
        self.logger = logging.LoggerAdapter(
            logging.getLogger("parallel_model.session"),
            {"session_id": session_id, "rv2v_session_id": self.rv2v_session_id},
        )

    async def start(self, message: StartMessage) -> None:
        if self.model_task is not None and not self.model_task.done():
            await self.send_json(error_message("SESSION_BUSY", "当前会话已经在运行"))
            return
        self.state = "connecting_model"
        await self.send_json({"type": "render_status", "state": self.state})
        client = JoyAIModelClient(
            self.settings,
            message,
            self.frames,
            self._on_model_event,
            self._on_model_frame,
            self.logger,
        )
        self.model_task = asyncio.create_task(self._run_model(client), name=self.rv2v_session_id)

    def set_pending_frame(self, meta: dict[str, Any]) -> bool:
        if self.pending_frame_meta is not None:
            return False
        self.pending_frame_meta = meta
        return True

    async def accept_frame(self, data: bytes) -> None:
        meta = self.pending_frame_meta
        self.pending_frame_meta = None
        if meta is None:
            await self.send_json(error_message("INVALID_MESSAGE", "二进制帧缺少 input_frame 元信息"))
            return
        if self.state != "running":
            await self.send_json(error_message("SESSION_NOT_READY", "模型尚未进入 running 状态"))
            return
        if not data.startswith(b"\xff\xd8"):
            await self.send_json(error_message("INVALID_FRAME", "输入数据不是 JPEG"))
            return
        if isinstance(meta.get("t_capture_ms"), int):
            self.capture_times[meta["seq"]] = meta["t_capture_ms"]
            if len(self.capture_times) > 240:
                oldest_seq = min(self.capture_times)
                self.capture_times.pop(oldest_seq, None)
        self.frames.put(
            InputFrame(
                seq=meta["seq"],
                data=data,
                t_capture_ms=meta.get("t_capture_ms"),
            )
        )

    async def stop(self, reason: str = "client_request") -> None:
        if self.state in {"stopping", "stopped"}:
            return
        self.state = "stopping"
        self.frames.close()
        if self.model_task is not None:
            self.model_task.cancel()
            await asyncio.gather(self.model_task, return_exceptions=True)
        self.state = "stopped"
        if reason != "client_disconnected":
            await self.send_json(
                {
                    "type": "virtual_tryon_stop",
                    "rv2v_session_id": self.rv2v_session_id,
                    "reason": reason,
                }
            )

    async def send_json(self, payload: dict[str, Any]) -> None:
        async with self._send_lock:
            await self.websocket.send_json(payload)

    async def _run_model(self, client: JoyAIModelClient) -> None:
        try:
            await client.run()
        except asyncio.CancelledError:
            await client.stop()
            raise
        except (OSError, TimeoutError, websockets.WebSocketException) as exc:
            self.state = "error"
            self.logger.exception("model connection failed")
            await self.send_json(error_message("MODEL_UNREACHABLE", str(exc)))
        except ModelProtocolError as exc:
            self.state = "error"
            self.logger.exception("model protocol failed")
            await self.send_json(error_message("MODEL_ERROR", str(exc)))
        except Exception as exc:
            self.state = "error"
            self.logger.exception("unexpected model failure")
            await self.send_json(error_message("INTERNAL_ERROR", str(exc), False))

    async def _on_model_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        if event_type == "queue_position":
            self.state = "queued"
            await self.send_json(
                {
                    "type": "render_status",
                    "state": "queued",
                    "position": event.get("position"),
                    "ahead": event.get("ahead"),
                }
            )
        elif event_type == "session_granted":
            self.state = "starting"
            await self.send_json({"type": "render_status", "state": "starting"})
        elif event_type == "started":
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
                        "width": event.get("width", self.settings.model_width),
                        "height": event.get("height", self.settings.model_height),
                        "fps": self.settings.model_fps,
                    },
                }
            )
        else:
            await self.send_json({"type": "model_event", "event": event})

    async def _on_model_frame(self, meta: dict[str, Any], data: bytes) -> None:
        now_ms = int(time.time() * 1000)
        source_seq = meta.get("source_seq")
        capture_ms = self.capture_times.pop(source_seq, None)
        payload = {
            "type": "output_frame",
            "source_seq": source_seq,
            "t_capture_ms": capture_ms,
            "t_output_ms": now_ms,
            "latency_ms": now_ms - capture_ms if isinstance(capture_ms, int) else None,
            "mime_type": "image/jpeg",
        }
        async with self._send_lock:
            await self.websocket.send_json(payload)
            await self.websocket.send_bytes(data)


import websockets
