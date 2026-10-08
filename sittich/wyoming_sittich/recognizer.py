"""German speech recognition with parakeet-primeline via sherpa-onnx (CPU only).

The decoding details (gain for quiet input, splitting long audio) follow
dictate's local_stt.py (https://github.com/winidi/dictate, MIT).
"""

import threading
from pathlib import Path
from typing import Iterator, Optional

import numpy as np

SAMPLE_RATE = 16000

# Quiet input (speech around -45 dBFS) comes back empty; raised to a peak of
# 0.5 it decodes fine. The gain is capped so room noise stays noise.
TARGET_PEAK = 0.5
MAX_GAIN = 30.0

# The encoder fails on more than ~400 s of audio and its memory grows
# quadratically before that, so long audio is decoded in pieces.
MAX_CHUNK_S = 90.0
RETRY_CHUNK_S = 20.0  # second pass for a long piece that came back empty
_SEARCH_S = 15.0  # look for a pause in the last part of each piece
_WIN_S = 0.4


class Recognizer:
    """Wraps sherpa_onnx.OfflineRecognizer; decodes are serialized by a lock.

    Hotwords need beam search, which costs about 100 ms more per command, so
    greedy search is used when they are off.
    """

    def __init__(
        self,
        model_dir: Path,
        num_threads: int,
        hotwords: bool = False,
        hotwords_score: float = 2.0,
    ) -> None:
        import sherpa_onnx

        decoding = {"decoding_method": "greedy_search"}
        if hotwords:
            decoding = {
                "decoding_method": "modified_beam_search",
                "hotwords_score": hotwords_score,
                "modeling_unit": "bpe",
                "bpe_vocab": str(model_dir / "bpe.vocab"),
            }
        self._recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=str(model_dir / "encoder.int8.onnx"),
            decoder=str(model_dir / "decoder.int8.onnx"),
            joiner=str(model_dir / "joiner.int8.onnx"),
            tokens=str(model_dir / "tokens.txt"),
            model_type="nemo_transducer",
            num_threads=num_threads,
            **decoding,
        )
        self._lock = threading.Lock()

        # The first decodes are about twice as slow; get them out of the way
        # before the first real request.
        for _ in range(2):
            self._decode(np.zeros(SAMPLE_RATE, dtype=np.float32))

    def transcribe(self, pcm: bytes, hotwords: Optional[str] = None) -> str:
        """Transcribe 16 kHz, 16-bit, mono PCM.

        hotwords: names separated by "/" (only used with hotwords enabled).
        """
        pcm = pcm[: len(pcm) - len(pcm) % 2]  # a stray odd byte would not be a sample
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        if len(audio) == 0:
            return ""

        parts = []
        with self._lock:
            for chunk in split_audio(audio):
                text = self._decode(chunk, hotwords)
                # A long piece that clearly holds speech now and then comes
                # back empty; shorter pieces of the same audio decode.
                if not text and len(chunk) > RETRY_CHUNK_S * SAMPLE_RATE:
                    pieces = split_audio(chunk, RETRY_CHUNK_S)
                    text = " ".join(
                        t for t in (self._decode(p, hotwords) for p in pieces) if t
                    )
                parts.append(text)
        return " ".join(p for p in parts if p)

    def _decode(self, chunk: np.ndarray, hotwords: Optional[str] = None) -> str:
        chunk = normalize_gain(chunk)
        stream = self._recognizer.create_stream(hotwords=hotwords)
        stream.accept_waveform(SAMPLE_RATE, chunk)
        self._recognizer.decode_stream(stream)
        return stream.result.text.strip()


def normalize_gain(audio: np.ndarray) -> np.ndarray:
    peak = float(np.abs(audio).max()) if len(audio) else 0.0
    if 0.0 < peak < TARGET_PEAK:
        return audio * min(TARGET_PEAK / peak, MAX_GAIN)
    return audio


def split_audio(audio: np.ndarray, max_s: float = MAX_CHUNK_S) -> Iterator[np.ndarray]:
    """Yield pieces of at most max_s seconds, cut at the quietest spot near the end."""
    search_s = min(_SEARCH_S, max_s / 2)
    max_n, search_n, win_n = (int(x * SAMPLE_RATE) for x in (max_s, search_s, _WIN_S))
    while len(audio) > max_n:
        tail = audio[max_n - search_n : max_n]
        n_win = len(tail) // win_n
        energy = (tail[: n_win * win_n].reshape(n_win, win_n) ** 2).mean(axis=1)
        cut = max_n - search_n + int(energy.argmin()) * win_n + win_n // 2
        yield audio[:cut]
        audio = audio[cut:]
    yield audio
