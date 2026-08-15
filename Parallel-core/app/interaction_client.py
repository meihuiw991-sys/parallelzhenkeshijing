import base64
import logging
from collections.abc import Sequence

import httpx

from app.config import Settings


class InteractionError(RuntimeError):
    pass


class InteractionSilence(InteractionError):
    pass


class InteractionClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def analyze(self, session_id: str, question: str, frames: Sequence[bytes]) -> str:
        if not frames:
            raise InteractionError("当前没有可用于分析的视频画面")

        latest_frame = frames[-1]
        encoded = base64.b64encode(latest_frame).decode("ascii")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.settings.assistant_api_key}",
            "x-streaming-session": session_id,
        }
        logger = logging.getLogger(__name__)
        logger.info(
            "Interaction request session=%s question=%r frames=%s frame_bytes=%s",
            session_id,
            question,
            1,
            [len(latest_frame)],
        )
        logger.info(
            "Interaction routing url=%s model=%s",
            self.settings.interaction_url,
            self.settings.interaction_model,
        )

        async with httpx.AsyncClient(timeout=self.settings.interaction_timeout_seconds) as client:
            for attempt, request_question in enumerate(
                (question, self.explicit_visual_retry_question(question)),
                start=1,
            ):
                content: list[dict[str, object]] = [
                    {"type": "text", "text": request_question},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
                    },
                ]
                payload: dict[str, object] = {
                    "model": self.settings.interaction_model,
                    "messages": [{"role": "user", "content": content}],
                }
                try:
                    response = await client.post(self.settings.interaction_url, headers=headers, json=payload)
                    response.raise_for_status()
                except httpx.TimeoutException as exc:
                    raise InteractionError("视觉分析超时，请稍后再试") from exc
                except httpx.HTTPError as exc:
                    response = getattr(exc, "response", None)
                    detail = ""
                    if response is not None:
                        body = response.text[:500].strip()
                        request_id = (
                            response.headers.get("x-request-id")
                            or response.headers.get("x-jdcloud-request-id")
                            or response.headers.get("x-bce-request-id")
                        )
                        detail = f"; request_id={request_id}; response={body!r}"
                    raise InteractionError(f"视觉分析服务不可用: {exc}{detail}") from exc

                try:
                    raw_content = response.json()["choices"][0]["message"]["content"]
                except (KeyError, IndexError, TypeError, ValueError) as exc:
                    raise InteractionError("视觉分析返回格式异常") from exc

                result = self.normalize_output(str(raw_content))
                if result:
                    logger.info(
                        "Interaction response session=%s result_length=%s attempt=%s",
                        session_id,
                        len(result),
                        attempt,
                    )
                    return result
                if attempt == 1:
                    logger.warning(
                        "Interaction returned silence; retrying explicit visual request session=%s question=%r",
                        session_id,
                        question,
                    )

        raise InteractionSilence("视觉模型连续两次未返回视觉结果")

    @staticmethod
    def explicit_visual_retry_question(question: str) -> str:
        return (
            "这是一个明确需要读取图片内容的视觉理解问题。"
            "请直接根据所附当前摄像头画面回答，不要返回 </silence>，不要脱离图片猜测。"
            f"用户问题：{question}"
        )

    @staticmethod
    def normalize_output(content: str) -> str:
        text = content.strip()
        if text == "</silence>":
            return ""
        if text.startswith("</response>"):
            return text.removeprefix("</response>").strip()
        return text
