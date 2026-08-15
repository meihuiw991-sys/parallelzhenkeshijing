from typing import Protocol


class VoiceUnderstandingService(Protocol):
    async def start(self, session_id: str) -> None: ...

    async def stop(self, session_id: str) -> None: ...


class DisabledVoiceUnderstandingService:
    enabled = False

    async def start(self, session_id: str) -> None:
        raise RuntimeError("voice understanding is not enabled")

    async def stop(self, session_id: str) -> None:
        return None
