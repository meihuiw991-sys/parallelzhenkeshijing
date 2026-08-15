import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from app.config import get_settings
from app.assistant_session import AssistantSession
from app.schemas import InputFrameMessage, PingMessage, StartMessage, StopMessage, error_message
from app.session import RenderSession

settings = get_settings()
logging.basicConfig(level=settings.log_level.upper())
active_sessions: dict[str, RenderSession] = {}
active_assistant_sessions: dict[str, AssistantSession] = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await _stop_all_sessions()


app = FastAPI(title="Parallel Model Render Gateway", lifespan=lifespan)
STATIC_DIR = Path(__file__).parent / "static"
PROMPT_FILE = Path(__file__).resolve().parents[1] / "prompts" / "video-edit.txt"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(
        STATIC_DIR / "index.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@app.get("/api/config/video-edit")
async def video_edit_config() -> dict[str, str]:
    try:
        prompt = PROMPT_FILE.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise HTTPException(status_code=500, detail="无法读取视频编辑 prompt") from exc
    if not prompt:
        raise HTTPException(status_code=500, detail="视频编辑 prompt 不能为空")
    return {"prompt": prompt}


@app.get("/api/capabilities")
async def capabilities() -> dict[str, dict[str, bool]]:
    return {
        "video_edit": {"enabled": True},
        "voice_understanding": {"enabled": True},
        "visual_interaction": {"enabled": True},
    }


@app.get("/api/health")
async def health() -> dict[str, Any]:
    reachable = False
    detail: dict[str, Any] | None = None
    try:
        headers = {"Authorization": f"Bearer {settings.model_api_key}"} if settings.model_api_key else {}
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(settings.model_health_url, headers=headers)
            reachable = response.is_success
            if response.headers.get("content-type", "").startswith("application/json"):
                detail = response.json()
    except httpx.HTTPError:
        pass
    return {
        "ok": True,
        "model_mode": "real",
        "model_reachable": reachable,
        "active_sessions": len(active_sessions),
        "active_assistant_sessions": len(active_assistant_sessions),
        "model": detail,
    }


@app.websocket("/ws/render/{session_id}")
async def render_websocket(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    if session_id in active_sessions:
        await websocket.send_json(error_message("SESSION_BUSY", "session_id 已被占用", False))
        await websocket.close(code=1008)
        return

    session = RenderSession(session_id, websocket, settings)
    active_sessions[session_id] = session
    await session.send_json({"type": "system", "event": "connected", "session_id": session_id})
    try:
        while True:
            packet = await websocket.receive()
            if packet.get("type") == "websocket.disconnect":
                break
            if packet.get("bytes") is not None:
                await session.accept_frame(packet["bytes"])
                continue
            text = packet.get("text")
            if text is not None:
                await _handle_text(session, text)
    except WebSocketDisconnect:
        pass
    finally:
        await session.stop("client_disconnected")
        active_sessions.pop(session_id, None)


@app.websocket("/ws/assistant/{session_id}")
async def assistant_websocket(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    if session_id in active_assistant_sessions:
        await websocket.send_json(error_message("SESSION_BUSY", "assistant session_id 已被占用", False))
        await websocket.close(code=1008)
        return

    session = AssistantSession(session_id, websocket, settings)
    active_assistant_sessions[session_id] = session
    try:
        await session.start()
        while True:
            payload = await websocket.receive_json()
            await session.accept_message(payload)
    except WebSocketDisconnect:
        pass
    except (json.JSONDecodeError, ValidationError):
        await websocket.send_json(error_message("INVALID_MESSAGE", "assistant 消息格式错误"))
    finally:
        await session.stop()
        active_assistant_sessions.pop(session_id, None)


async def _handle_text(session: RenderSession, text: str) -> None:
    try:
        payload = json.loads(text)
        message_type = payload.get("type")
        if message_type == "start_stream_edit":
            await session.start(StartMessage.model_validate(payload))
        elif message_type == "input_frame":
            message = InputFrameMessage.model_validate(payload)
            if not session.set_pending_frame(message.model_dump()):
                await session.send_json(error_message("INVALID_MESSAGE", "上一帧尚未收到二进制数据"))
        elif message_type == "tryon_stop":
            StopMessage.model_validate(payload)
            await session.stop()
        elif message_type == "ping":
            message = PingMessage.model_validate(payload)
            await session.send_json({"type": "pong", "t": message.t})
        else:
            await session.send_json(error_message("INVALID_MESSAGE", f"未知消息类型: {message_type}"))
    except (json.JSONDecodeError, ValidationError) as exc:
        await session.send_json(error_message("INVALID_MESSAGE", str(exc)))


async def _stop_all_sessions() -> None:
    for session in list(active_sessions.values()):
        await session.stop("server_shutdown")
    active_sessions.clear()
    for session in list(active_assistant_sessions.values()):
        await session.stop()
    active_assistant_sessions.clear()
