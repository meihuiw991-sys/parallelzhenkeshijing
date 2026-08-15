import os
from functools import lru_cache
from pathlib import Path

from dotenv import dotenv_values
from pydantic import BaseModel, Field


class Settings(BaseModel):
    model_ws_url: str
    model_health_url: str
    model_api_key: str = ""
    model_api_key_2: str = ""
    model_width: int = 1248
    model_height: int = 720
    model_fps: int = 24
    model_input_codec: str = "mjpeg"
    model_output_codec: str = "mjpeg"
    model_output_quality: int = Field(default=85, ge=1, le=100)
    model_gate_enabled: bool = False
    model_use_pe: bool = False
    talker_ws_url: str = "ws://hubrouter.jd.com/v1/realtime?model=JoyAI-Talker"
    voice_ws_url: str = "ws://hubrouter.jd.com/v1/realtime?model=JoyAI-Voice"
    voice_name: str = "default"
    voice_output_sample_rate: int = 24000
    voice_timeout_seconds: float = Field(default=30, gt=0, le=120)
    interaction_url: str = "https://hubrouter.jd.com/v1/chat/completions"
    interaction_reset_url: str = "https://hubrouter.jd.com/v1/streaming/reset"
    interaction_model: str = "JoyAI-VL-Interaction"
    interaction_timeout_seconds: float = Field(default=20, gt=0, le=60)
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    log_level: str = "INFO"

    @property
    def assistant_api_key(self) -> str:
        return self.model_api_key_2 or self.model_api_key


@lru_cache
def get_settings() -> Settings:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    file_values = {key: value for key, value in dotenv_values(env_path).items() if value is not None}
    merged = {**file_values, **os.environ}
    fields = Settings.model_fields
    values = {
        field_name: merged[alias]
        for field_name in fields
        if (alias := field_name.upper()) in merged
    }
    return Settings.model_validate(values)
