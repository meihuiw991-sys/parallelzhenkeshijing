import argparse
import asyncio
import base64
import json
import os
import wave
from pathlib import Path

import websockets
from dotenv import dotenv_values


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_URL = "ws://hubrouter.jd.com/v1/realtime?model=JoyAI-Voice"


def load_api_key() -> tuple[str, str]:
    env_values = dotenv_values(PROJECT_ROOT / ".env")
    api_key = os.getenv("MODEL_API_KEY_2") or env_values.get("MODEL_API_KEY_2")
    if api_key:
        return str(api_key), "MODEL_API_KEY_2"
    fallback = os.getenv("MODEL_API_KEY") or env_values.get("MODEL_API_KEY")
    if fallback:
        return str(fallback), "MODEL_API_KEY"
    raise RuntimeError("未在环境变量或 .env 中找到 MODEL_API_KEY_2 / MODEL_API_KEY")


def save_wav(path: Path, pcm: bytes, sample_rate: int) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(pcm)


async def voice_synth(url: str, text: str, output_path: Path) -> None:
    api_key, key_source = load_api_key()
    sample_rate = 24000
    print(f"连接 Voice: {url}")
    print(f"鉴权来源: {key_source}，Key 长度: {len(api_key)}")

    async with websockets.connect(
        url,
        subprotocols=["realtime"],
        additional_headers={"Authorization": f"Bearer {api_key}"},
        max_size=None,
        open_timeout=20,
    ) as websocket:
        await websocket.send(
            json.dumps(
                {
                    "type": "session.update",
                    "session": {
                        "modalities": ["text", "audio"],
                        "voice": "default",
                        "input_audio_format": "pcm16",
                        "output_audio_format": "pcm16",
                        "output_sample_rate": sample_rate,
                        "voice_cfg": {},
                    },
                },
                ensure_ascii=False,
            )
        )
        print("已发送 session.update")

        text_sent = False
        audio_chunks: list[bytes] = []
        async for message in websocket:
            if not isinstance(message, str):
                print(f"收到非文本 WebSocket 消息: {len(message)} 字节")
                continue
            event = json.loads(message)
            event_type = event.get("type")
            if event_type != "response.output_audio.delta":
                print("服务端事件:", json.dumps(event, ensure_ascii=False))

            if event_type in {"session.created", "session.updated"} and not text_sent:
                await websocket.send(
                    json.dumps(
                        {
                            "type": "conversation.item.create",
                            "item": {
                                "type": "tts_text",
                                "content": [{"type": "text", "text": text}],
                            },
                        },
                        ensure_ascii=False,
                    )
                )
                text_sent = True
                print(f"已发送 tts_text: {text}")
            elif event_type == "response.output_audio.delta":
                audio = event.get("delta")
                if isinstance(audio, str):
                    audio_chunks.append(base64.b64decode(audio))
                    if len(audio_chunks) == 1 or len(audio_chunks) % 20 == 0:
                        print(f"已收到音频分片: {len(audio_chunks)}")
            elif event_type == "response.done":
                break
            elif event_type == "error":
                raise RuntimeError(json.dumps(event, ensure_ascii=False))

    pcm = b"".join(audio_chunks)
    if not pcm:
        raise RuntimeError("Voice 返回 response.done，但没有收到音频数据")
    save_wav(output_path, pcm, sample_rate)
    print(f"成功收到 {len(pcm)} 字节 PCM 音频")
    print(f"WAV 已保存到: {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="测试 JoyAI Voice WebSocket TTS 连通性")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--text", default="您好，欢迎体验 JoyAI 语音合成。")
    parser.add_argument("--output", default="voice-test.wav")
    args = parser.parse_args()
    asyncio.run(voice_synth(args.url, args.text, PROJECT_ROOT / args.output))


if __name__ == "__main__":
    main()
