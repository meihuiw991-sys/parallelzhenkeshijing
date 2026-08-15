from app.interaction_client import InteractionClient
from app.config import Settings


def test_normalize_interaction_response() -> None:
    assert InteractionClient.normalize_output("</response> 画面中有一位穿黑色外套的人。") == "画面中有一位穿黑色外套的人。"


def test_normalize_interaction_silence() -> None:
    assert InteractionClient.normalize_output("</silence>") == ""


def test_interaction_uses_provider_model_name() -> None:
    settings = Settings(
        model_ws_url="wss://example.test/ws",
        model_health_url="https://example.test/health",
        interaction_model="JoyAI-VL-Interaction",
    )

    assert settings.interaction_model == "JoyAI-VL-Interaction"


def test_explicit_visual_retry_forbids_silence() -> None:
    retry = InteractionClient.explicit_visual_retry_question("画面中有几个人")

    assert "画面中有几个人" in retry
    assert "不要返回 </silence>" in retry
    assert "当前摄像头画面" in retry
