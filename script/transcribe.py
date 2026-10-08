#!/usr/bin/env python3
"""Send WAV files to a Wyoming STT server and print transcript and latency.

    python3 script/transcribe.py --uri tcp://192.168.1.10:10300 aufnahme.wav
"""

import argparse
import asyncio
import time
import wave

from wyoming.asr import Transcribe, Transcript
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.client import AsyncClient

CHUNK_SAMPLES = 1024


async def transcribe(uri: str, path: str) -> tuple[str, float, float]:
    with wave.open(path, "rb") as wav:
        rate, width, channels = wav.getframerate(), wav.getsampwidth(), wav.getnchannels()
        frames = wav.readframes(wav.getnframes())
        duration = wav.getnframes() / rate

    async with AsyncClient.from_uri(uri) as client:
        await client.write_event(Transcribe(language="de").event())
        await client.write_event(AudioStart(rate, width, channels).event())
        step = CHUNK_SAMPLES * width * channels
        for i in range(0, len(frames), step):
            chunk = AudioChunk(rate, width, channels, frames[i : i + step])
            await client.write_event(chunk.event())
        start = time.monotonic()
        await client.write_event(AudioStop().event())

        while True:
            event = await client.read_event()
            if event is None:
                raise ConnectionError("Server closed the connection without a transcript")
            if Transcript.is_type(event.type):
                return Transcript.from_event(event).text, duration, time.monotonic() - start


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--uri", default="tcp://127.0.0.1:10300")
    parser.add_argument("wav", nargs="+")
    args = parser.parse_args()

    for path in args.wav:
        text, duration, latency = await transcribe(args.uri, path)
        print(f"{path}  ({duration:.1f} s audio, {latency * 1000:.0f} ms)\n  -> {text}")


if __name__ == "__main__":
    asyncio.run(main())
