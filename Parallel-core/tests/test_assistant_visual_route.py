import asyncio

from app.assistant_session import AssistantSession
from app.config import Settings


class FakeWebSocket:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.messages.append(payload)


def test_normal_visual_question_still_calls_interaction_and_voice() -> None:
    async def scenario() -> None:
        websocket = FakeWebSocket()
        settings = Settings(
            model_ws_url="wss://example.test/ws",
            model_health_url="https://example.test/health",
            model_api_key_2="test-key",
        )
        session = AssistantSession("test-session", websocket, settings)
        interaction_calls: list[str] = []
        spoken_texts: list[str] = []

        async def analyze(session_id: str, question: str, frames: list[bytes]) -> str:
            interaction_calls.append(question)
            return "真实视觉模型返回内容"

        async def synthesize(text: str) -> None:
            spoken_texts.append(text)

        session.interaction.analyze = analyze
        session.voice.synthesize = synthesize
        session._automatic_response_started.set()

        await session._run_deterministic_visual_route("请介绍一下视频的内容")

        assert interaction_calls == ["请介绍一下视频的内容"]
        assert spoken_texts == ["真实视觉模型返回内容"]
        assert {
            "type": "vision_analysis",
            "state": "completed",
            "question": "请介绍一下视频的内容",
            "result": "真实视觉模型返回内容",
        } in websocket.messages

    asyncio.run(scenario())
