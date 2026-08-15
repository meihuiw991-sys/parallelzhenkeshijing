import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import websockets
from websockets.asyncio.client import ClientConnection

from app.config import Settings
from app.frame_buffer import LatestFrameBuffer
from app.schemas import StartMessage

JsonHandler = Callable[[dict[str, Any]], Awaitable[None]]
FrameHandler = Callable[[dict[str, Any], bytes], Awaitable[None]]


class ModelProtocolError(RuntimeError):
    pass


class JoyAIModelClient:
    def __init__(
        self,
        settings: Settings,
        start: StartMessage,
        frames: LatestFrameBuffer,
        on_event: JsonHandler,
        on_frame: FrameHandler,
        logger: logging.LoggerAdapter,
    ) -> None:
        self.settings = settings
        self.start = start
        self.frames = frames
        self.on_event = on_event
        self.on_frame = on_frame
        self.logger = logger
        self._ws: ClientConnection | None = None
        self._stop = asyncio.Event()

    async def run(self) -> None:
        headers = {}
        if self.settings.model_api_key:
            headers["Authorization"] = f"Bearer {self.settings.model_api_key}"

        async with websockets.connect(
            self.settings.model_ws_url,
            additional_headers=headers,
            max_size=None,
            open_timeout=20,
            ping_interval=20,
            ping_timeout=20,
        ) as ws:
            self._ws = ws
            await self._wait_for_grant(ws)
            await ws.send(json.dumps(self._build_start_payload()))
            started = await self._wait_for_started(ws)
            await self.on_event(started)

            sender = asyncio.create_task(self._send_frames(ws), name="model-frame-sender")
            receiver = asyncio.create_task(self._receive_frames(ws), name="model-frame-receiver")
            done, pending = await asyncio.wait(
                {sender, receiver}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                task.result()

    async def stop(self) -> None:
        self._stop.set()
        self.frames.close()
        if self._ws is not None:
            try:
                await self._ws.send(json.dumps({"type": "stop"}))
            except websockets.ConnectionClosed:
                pass

    async def _wait_for_grant(self, ws: ClientConnection) -> None:
        while not self._stop.is_set():
            message = await ws.recv()
            if not isinstance(message, str):
                raise ModelProtocolError("模型在启动前返回了意外二进制消息")
            event = json.loads(message)
            event_type = event.get("type")
            if event_type == "session_granted":
                await self.on_event(event)
                return
            await self.on_event(event)
            if event_type in {"error", "session_timeout"}:
                raise ModelProtocolError(str(event))
        raise asyncio.CancelledError

    async def _wait_for_started(self, ws: ClientConnection) -> dict[str, Any]:
        while not self._stop.is_set():
            message = await ws.recv()
            if not isinstance(message, str):
                raise ModelProtocolError("模型在 started 前返回了意外二进制消息")
            event = json.loads(message)
            if event.get("type") == "started":
                return event
            await self.on_event(event)
            if event.get("type") in {"error", "session_timeout"}:
                raise ModelProtocolError(str(event))
        raise asyncio.CancelledError

    def _build_start_payload(self) -> dict[str, Any]:
        options = self.start.options
        payload: dict[str, Any] = {
            "type": "start",
            "prompt": self.start.prompt,
            "output_quality": options.output_quality or self.settings.model_output_quality,
            "gate_enabled": (
                options.gate_enabled
                if options.gate_enabled is not None
                else self.settings.model_gate_enabled
            ),
            "use_pe": options.use_pe if options.use_pe is not None else self.settings.model_use_pe,
            "width": self.settings.model_width,
            "height": self.settings.model_height,
            "input_codec": self.settings.model_input_codec,
            "output_codec": self.settings.model_output_codec,
        }
        for key in ("seed", "num_inference_steps", "ref_image"):
            value = getattr(options, key)
            if value is not None:
                payload[key] = value
        return payload

    async def _send_frames(self, ws: ClientConnection) -> None:
        while not self._stop.is_set():
            frame = await self.frames.get()
            if frame is None:
                return
            meta = {"type": "frame_meta", "seq": frame.seq}
            if frame.t_capture_ms is not None:
                meta["t_capture_ms"] = frame.t_capture_ms
            await ws.send(json.dumps(meta))
            await ws.send(frame.data)

    async def _receive_frames(self, ws: ClientConnection) -> None:
        pending: dict[str, Any] | None = None
        while not self._stop.is_set():
            message = await ws.recv()
            if isinstance(message, bytes):
                if pending is None:
                    raise ModelProtocolError("模型二进制帧缺少 output_frame 元信息")
                await self.on_frame(pending, message)
                pending = None
                continue

            event = json.loads(message)
            event_type = event.get("type")
            if event_type == "output_frame":
                if pending is not None:
                    raise ModelProtocolError("连续收到 output_frame，上一帧缺少二进制数据")
                pending = event
            else:
                await self.on_event(event)
                if event_type in {"error", "session_timeout"}:
                    raise ModelProtocolError(str(event))

