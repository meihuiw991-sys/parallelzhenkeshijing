import pytest
from pydantic import ValidationError

from app.schemas import InputFrameMessage, StartMessage


def test_prompt_is_required() -> None:
    with pytest.raises(ValidationError):
        StartMessage.model_validate({"type": "start_stream_edit", "prompt": ""})


def test_only_jpeg_input_is_accepted() -> None:
    with pytest.raises(ValidationError):
        InputFrameMessage.model_validate(
            {"type": "input_frame", "seq": 1, "mime_type": "video/h264"}
        )

