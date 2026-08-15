import asyncio
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import websockets
from websockets.asyncio.client import ClientConnection

from app.config import Settings

EventHandler = Callable[[dict[str, Any]], Awaitable[None]]
ToolHandler = Callable[[str, dict[str, Any]], Awaitable[str]]


class TalkerProtocolError(RuntimeError):
    pass


class TalkerClient:
    def __init__(
        self,
        settings: Settings,
        on_event: EventHandler,
        on_tool_call: ToolHandler,
        logger: logging.LoggerAdapter,
    ) -> None:
        self.settings = settings
        self.on_event = on_event
        self.on_tool_call = on_tool_call
        self.logger = logger
        self.audio_queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=12)
        self._ws: ClientConnection | None = None
        self._stop = asyncio.Event()
        self._ready = asyncio.Event()
        self._session_initialized = False
        self._created_fallback_task: asyncio.Task[None] | None = None
        self._tool_tasks: set[asyncio.Task[None]] = set()

    async def run(self) -> None:
        api_key = self.settings.assistant_api_key
        headers = {"Authorization": f"Bearer {api_key}"}
        key_source = "MODEL_API_KEY_2" if self.settings.model_api_key_2 else "MODEL_API_KEY"
        key_fingerprint = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:8] if api_key else "empty"
        self.logger.info(
            "connecting to Talker url=%s key_source=%s key_length=%s key_fingerprint=%s",
            self.settings.talker_ws_url,
            key_source,
            len(api_key),
            key_fingerprint,
        )
        async with websockets.connect(
            self.settings.talker_ws_url,
            subprotocols=["realtime"],
            additional_headers=headers,
            max_size=None,
            open_timeout=20,
            ping_interval=20,
            ping_timeout=20,
        ) as websocket:
            self._ws = websocket
            self.logger.info("Talker websocket connected; sending session.update")
            await websocket.send(json.dumps(self._session_update()))
            sender = asyncio.create_task(self._send_audio(websocket), name="talker-audio-sender")
            readiness = asyncio.create_task(self._watch_readiness(), name="talker-readiness-watchdog")
            try:
                async for raw_message in websocket:
                    if not isinstance(raw_message, str):
                        continue
                    event = json.loads(raw_message)
                    event_type = event.get("type")
                    if event_type not in {"response.output_audio.delta", "response.audio.delta"}:
                        self.logger.info("Talker raw event type=%s", event_type)
                    await self._handle_event(websocket, event)
                    if self._stop.is_set():
                        break
            finally:
                sender.cancel()
                readiness.cancel()
                if self._created_fallback_task is not None:
                    self._created_fallback_task.cancel()
                await asyncio.gather(sender, readiness, return_exceptions=True)
                for task in self._tool_tasks:
                    task.cancel()
                await asyncio.gather(*self._tool_tasks, return_exceptions=True)

    async def append_audio(self, audio_base64: str) -> None:
        if self.audio_queue.full():
            try:
                self.audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        self.audio_queue.put_nowait(audio_base64)

    async def cancel_response(self) -> None:
        websocket = self._ws
        if websocket is None or self._stop.is_set():
            return
        self.logger.info("cancelling Talker automatic response")
        await websocket.send(json.dumps({"type": "response.cancel"}))

    async def respond_with_visual_result(self, question: str, result: str) -> None:
        websocket = self._ws
        if websocket is None or self._stop.is_set():
            return
        injected_text = (
            "以下是视觉分析工具对用户当前画面的真实分析结果。"
            "请仅依据该结果回答用户，不要补充结果中没有的视觉细节，也不要再次调用工具。\n"
            f"用户原问题：{question}\n"
            f"视觉分析结果：{result}"
        )
        self.logger.info(
            "injecting visual result into Talker question=%r result_length=%s",
            question,
            len(result),
        )
        await websocket.send(
            json.dumps(
                {
                    "type": "conversation.item.create",
                    "item": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": injected_text}],
                    },
                },
                ensure_ascii=False,
            )
        )
        await websocket.send(json.dumps({"type": "response.create"}))

    async def respond_to_text(self, question: str) -> None:
        websocket = self._ws
        if websocket is None or self._stop.is_set():
            return
        self.logger.info("replaying question to Talker without visual context question=%r", question)
        await websocket.send(
            json.dumps(
                {
                    "type": "conversation.item.create",
                    "item": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": question}],
                    },
                },
                ensure_ascii=False,
            )
        )
        await websocket.send(json.dumps({"type": "response.create"}))

    async def stop(self) -> None:
        self._stop.set()
        try:
            self.audio_queue.put_nowait(None)
        except asyncio.QueueFull:
            pass
        if self._ws is not None:
            try:
                await self._ws.close(code=1000, reason="client_stop")
            except websockets.ConnectionClosed:
                pass

    async def _handle_event(self, websocket: ClientConnection, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        if event_type == "session.created" and not self._session_initialized:
            self.logger.info("Talker session.created received; waiting for session.updated before tools")
            if self._created_fallback_task is None:
                self._created_fallback_task = asyncio.create_task(
                    self._register_after_created_fallback(websocket),
                    name="talker-created-fallback",
                )
            return
        if event_type == "session.updated" and not self._session_initialized:
            if self._created_fallback_task is not None:
                self._created_fallback_task.cancel()
                self._created_fallback_task = None
            await self._register_tools(websocket, "session.updated")
            return
        if event_type == "response.output_item.added":
            item = event.get("item")
            if isinstance(item, dict):
                self.logger.info(
                    "Talker output item added item_type=%s item_name=%s call_id=%s",
                    item.get("type"),
                    item.get("name"),
                    item.get("call_id"),
                )
        if event_type == "response.function_call_arguments.done":
            self.logger.info(
                "Talker function call name=%s call_id=%s arguments=%s",
                event.get("name"),
                event.get("call_id"),
                event.get("arguments"),
            )
            task = asyncio.create_task(self._execute_tool(websocket, event), name="talker-tool-call")
            self._tool_tasks.add(task)
            task.add_done_callback(self._tool_tasks.discard)
            return
        await self.on_event(event)

    async def _register_after_created_fallback(self, websocket: ClientConnection) -> None:
        await asyncio.sleep(1)
        if not self._session_initialized and not self._stop.is_set():
            self.logger.warning("Talker did not emit session.updated; using session.created fallback")
            await self._register_tools(websocket, "session.created_fallback")

    async def _register_tools(self, websocket: ClientConnection, ready_event: str) -> None:
        if self._session_initialized:
            return
        self._session_initialized = True
        self.logger.info("registering Talker tools after event=%s", ready_event)
        payload = self._tools_payload()
        await websocket.send(json.dumps(payload, ensure_ascii=False))
        self.logger.info(
            "Talker tools sent names=%s",
            [tool.get("name") for tool in payload["tools"]],
        )
        self._ready.set()
        await self.on_event({"type": "assistant_status", "state": "ready"})

    async def _watch_readiness(self) -> None:
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=10)
        except TimeoutError:
            self.logger.error("Talker session did not become ready within 10 seconds")
            await self.on_event(
                {
                    "type": "error",
                    "error": "Talker 已连接，但 10 秒内未返回 session.created/session.updated",
                }
            )

    async def _execute_tool(self, websocket: ClientConnection, event: dict[str, Any]) -> None:
        call_id = str(event.get("call_id", ""))
        name = str(event.get("name", ""))
        try:
            arguments = json.loads(event.get("arguments") or "{}")
        except json.JSONDecodeError:
            arguments = {}
        try:
            output = await self.on_tool_call(name, arguments)
        except Exception as exc:
            self.logger.exception("talker tool execution failed")
            output = f"工具执行失败：{exc}"
        if self._stop.is_set():
            return
        await websocket.send(
            json.dumps(
                {
                    "type": "conversation.item.create",
                    "item": {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": output,
                    },
                },
                ensure_ascii=False,
            )
        )

    async def _send_audio(self, websocket: ClientConnection) -> None:
        await self._ready.wait()
        self.logger.info("Talker audio sender ready")
        sent_count = 0
        while not self._stop.is_set():
            audio = await self.audio_queue.get()
            if audio is None:
                return
            await websocket.send(json.dumps({"type": "input_audio_buffer.append", "audio": audio}))
            sent_count += 1
            if sent_count == 1 or sent_count % 50 == 0:
                self.logger.info("audio chunk sent to Talker count=%s base64_length=%s", sent_count, len(audio))

    def _session_update(self) -> dict[str, Any]:
        prompt_path = Path(__file__).resolve().parents[1] / "prompts" / "talker.txt"
        prompt = prompt_path.read_text(encoding="utf-8").strip()
        return {
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "turn_detection": {"type": "server_vad"},
                "instructions": {"talker_prompt": prompt, "voice_prompt": ""},
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "sample_rate": 16000,
                "output_sample_rate": 24000,
                "s2t": {
                    "task_type": "QA",
                    "temperature": 0.4,
                    "max_tokens": 1024,
                    "top_p": 0.8,
                    "top_k": 20,
                    "repetition_penalty": 1.1,
                },
            },
        }

    @staticmethod
    def _tools_payload() -> dict[str, Any]:
        return {
            "type": "set_tools",
            "tools": [
                {
                    "type": "function",
                    "name": "describe_current_view",
                    "description": (
                        "当用户询问眼前、镜头、视频或画面中的人物、穿搭、地点、物体、动作、"
                        "环境或正在发生的事情时调用。不要凭空猜测视觉内容。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "question": {
                                "type": "string",
                                "description": "需要视觉模型根据当前画面回答的完整问题",
                            }
                        },
                        "required": ["question"],
                    },
                }
            ],
        }
