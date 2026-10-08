"""Wyoming event handler: collects audio, returns one transcript."""

import asyncio
import logging
import time
from typing import Optional

from wyoming.asr import Transcribe, Transcript
from wyoming.audio import AudioChunk, AudioChunkConverter, AudioStart, AudioStop
from wyoming.event import Event
from wyoming.info import Describe, Info
from wyoming.server import AsyncEventHandler

from .hotwords import HotwordSource
from .recognizer import SAMPLE_RATE, Recognizer

_LOGGER = logging.getLogger(__name__)

LANGUAGE = "de"

# Voice commands take a few seconds. The cap keeps a client that never stops
# sending from filling the memory (30 s of audio need about 1 GB to decode).
MAX_AUDIO_S = 30
_MAX_AUDIO_BYTES = MAX_AUDIO_S * SAMPLE_RATE * 2


class SittichEventHandler(AsyncEventHandler):
    def __init__(
        self,
        wyoming_info: Info,
        recognizer: Recognizer,
        hotword_source: Optional[HotwordSource],
        *args,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._info_event = wyoming_info.event()
        self._recognizer = recognizer
        self._hotword_source = hotword_source
        self._converter = AudioChunkConverter(rate=SAMPLE_RATE, width=2, channels=1)
        self._audio = bytearray()

    async def handle_event(self, event: Event) -> bool:
        if Describe.is_type(event.type):
            await self.write_event(self._info_event)
            return True

        if Transcribe.is_type(event.type):
            transcribe = Transcribe.from_event(event)
            # Accept regional variants such as de-DE, de-AT, de-CH.
            if transcribe.language and transcribe.language.split("-")[0] != LANGUAGE:
                _LOGGER.warning(
                    "Requested language %r, but this model only knows German",
                    transcribe.language,
                )
            return True

        if AudioStart.is_type(event.type):
            self._audio.clear()
            return True

        if AudioChunk.is_type(event.type):
            chunk = self._converter.convert(AudioChunk.from_event(event))
            room = _MAX_AUDIO_BYTES - len(self._audio)
            if room > 0:
                self._audio += chunk.audio[:room]
                if len(chunk.audio) > room:
                    _LOGGER.warning("Audio longer than %d s, ignoring the rest", MAX_AUDIO_S)
            return True

        if AudioStop.is_type(event.type):
            pcm = bytes(self._audio)
            self._audio.clear()

            hotwords = self._hotword_source.hotwords if self._hotword_source else None
            start = time.monotonic()
            text = await asyncio.get_running_loop().run_in_executor(
                None, self._recognizer.transcribe, pcm, hotwords
            )
            _LOGGER.info(
                "%.1f s audio -> %.0f ms: %s",
                len(pcm) / (2 * SAMPLE_RATE),
                (time.monotonic() - start) * 1000,
                text,
            )
            await self.write_event(Transcript(text=text, language=LANGUAGE).event())
            # One transcript per connection, like the other Wyoming STT servers.
            return False

        return True
