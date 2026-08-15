import asyncio

from app.frame_buffer import InputFrame, LatestFrameBuffer


def test_latest_frame_replaces_older_frame() -> None:
    async def scenario() -> None:
        buffer = LatestFrameBuffer()
        buffer.put(InputFrame(seq=1, data=b"first"))
        buffer.put(InputFrame(seq=2, data=b"latest"))

        frame = await asyncio.wait_for(buffer.get(), timeout=0.1)

        assert frame is not None
        assert frame.seq == 2
        assert frame.data == b"latest"

    asyncio.run(scenario())


def test_close_unblocks_waiter() -> None:
    async def scenario() -> None:
        buffer = LatestFrameBuffer()
        waiter = asyncio.create_task(buffer.get())

        buffer.close()

        assert await asyncio.wait_for(waiter, timeout=0.1) is None

    asyncio.run(scenario())
