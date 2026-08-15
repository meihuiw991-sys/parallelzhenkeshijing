from typing import Any, Literal

from pydantic import BaseModel, Field


class RenderOptions(BaseModel):
    output_quality: int | None = Field(default=None, ge=1, le=100)
    gate_enabled: bool | None = None
    use_pe: bool | None = None
    seed: int | None = None
    num_inference_steps: int | None = Field(default=None, ge=1)
    ref_image: str | None = None


class StartMessage(BaseModel):
    type: Literal["start_stream_edit"]
    prompt: str = Field(min_length=1)
    stream_key: str | None = None
    options: RenderOptions = Field(default_factory=RenderOptions)


class InputFrameMessage(BaseModel):
    type: Literal["input_frame"]
    seq: int = Field(ge=0)
    t_capture_ms: int | None = None
    mime_type: Literal["image/jpeg"] = "image/jpeg"


class StopMessage(BaseModel):
    type: Literal["tryon_stop"]
    rv2v_session_id: str | None = None


class PingMessage(BaseModel):
    type: Literal["ping"]
    t: int | float | None = None


def error_message(code: str, message: str, recoverable: bool = True) -> dict[str, Any]:
    return {
        "type": "error",
        "error_code": code,
        "message": message,
        "recoverable": recoverable,
    }

