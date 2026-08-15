import logging

from app.config import Settings
from app.frame_buffer import LatestFrameBuffer
from app.model_client import JoyAIModelClient
from app.schemas import StartMessage


async def _ignore_event(_: dict) -> None:
    pass


async def _ignore_frame(_: dict, __: bytes) -> None:
    pass


def make_settings() -> Settings:
    return Settings(
        model_ws_url="wss://example.test/ws",
        model_health_url="https://example.test/health",
        model_api_key="secret",
    )


def test_start_payload_uses_documented_mjpeg_defaults() -> None:
    start = StartMessage.model_validate(
        {
            "type": "start_stream_edit",
            "prompt": "watercolor",
            "options": {},
        }
    )
    client = JoyAIModelClient(
        make_settings(),
        start,
        LatestFrameBuffer(),
        _ignore_event,
        _ignore_frame,
        logging.LoggerAdapter(logging.getLogger(__name__), {}),
    )

    payload = client._build_start_payload()

    assert payload["type"] == "start"
    assert payload["prompt"] == "watercolor"
    assert payload["width"] == 1248
    assert payload["height"] == 720
    assert payload["input_codec"] == "mjpeg"
    assert payload["output_codec"] == "mjpeg"
    assert payload["gate_enabled"] is False


def test_start_payload_allows_supported_options() -> None:
    start = StartMessage.model_validate(
        {
            "type": "start_stream_edit",
            "prompt": "cinematic",
            "options": {
                "output_quality": 90,
                "use_pe": True,
                "seed": 42,
                "num_inference_steps": 4,
                "ref_image": "data:image/jpeg;base64,abc",
            },
        }
    )
    client = JoyAIModelClient(
        make_settings(),
        start,
        LatestFrameBuffer(),
        _ignore_event,
        _ignore_frame,
        logging.LoggerAdapter(logging.getLogger(__name__), {}),
    )

    payload = client._build_start_payload()

    assert payload["output_quality"] == 90
    assert payload["use_pe"] is True
    assert payload["seed"] == 42
    assert payload["num_inference_steps"] == 4
    assert payload["ref_image"].startswith("data:image/jpeg")

