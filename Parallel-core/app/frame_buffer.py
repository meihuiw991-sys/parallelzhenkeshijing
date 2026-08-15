import asyncio
from dataclasses import dataclass


@dataclass(slots=True)
class InputFrame:
    seq: int
    data: bytes
    t_capture_ms: int | None = None


class LatestFrameBuffer:
    def __init__(self) -> None:
        self._frame: InputFrame | None = None
        self._ready = asyncio.Event()
        self._closed = False

    def put(self, frame: InputFrame) -> None:
        if self._closed:
            return
        self._frame = frame
        self._ready.set()

    async def get(self) -> InputFrame | None:
        await self._ready.wait()
        if self._closed:
            return None
        frame = self._frame
        self._frame = None
        self._ready.clear()
        return frame

    def close(self) -> None:
        self._closed = True
        self._frame = None
        self._ready.set()

