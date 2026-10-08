"""The parakeet-primeline model files and their download, verified by SHA-256.

Standard library only: the Docker build runs this before any package is
installed, and nothing else is needed to fetch six files.

    python3 model.py /app/model
"""

import hashlib
import logging
import sys
import urllib.request
from pathlib import Path
from typing import NamedTuple

_LOGGER = logging.getLogger(__name__)

MODEL_NAME = "parakeet-primeline"
MODEL_REPO = "flozen1981/parakeet-primeline-onnx"
# Pinned commit: the files under this revision can never change.
MODEL_REVISION = "d548e25b9bfe559aa274f361892dc4ed5d64743a"
BASE_URL = f"https://huggingface.co/{MODEL_REPO}/resolve/{MODEL_REVISION}"


class ModelFile(NamedTuple):
    size: int
    sha256: str


MODEL_FILES = {
    "encoder.int8.onnx": ModelFile(
        1548009, "d4232f86718da0330167fb10789d1a35cffe6a60cd58239957943a8d9bc24c63"
    ),
    # ~620 MB of weights, must sit next to encoder.int8.onnx
    "encoder.int8.onnx.data": ModelFile(
        650776320, "d3b0d27912043d38a3c2ce4f2c03124be30bc1ff57d976302908954b2e8fe7bb"
    ),
    "decoder.int8.onnx": ModelFile(
        11845275, "fb4ddefe200706cabb27ee3fc1c81efa50555a4c8a8e00b663cc795216fb9369"
    ),
    "joiner.int8.onnx": ModelFile(
        6355277, "8220c0d117d81bdd0d8c770881932ac340f1ce4b36932941d561d11ad1aaffce"
    ),
    "tokens.txt": ModelFile(
        102132, "ba8e4007c65f4bb4358ffe2ecc13d9ccc7a10351151065242b5c3a943e685742"
    ),
    # only needed to encode hotwords
    "bpe.vocab": ModelFile(
        125600, "5f7869f9996291870418aa4c93bbf62957e4be7b3d842fc714328968830b5a67"
    ),
}

_CHUNK = 1024 * 1024


def model_installed(model_dir: Path) -> bool:
    """Cheap check (sizes only); hashes are verified once, at download."""
    return all(
        (model_dir / name).is_file() and (model_dir / name).stat().st_size == f.size
        for name, f in MODEL_FILES.items()
    )


def download_model(model_dir: Path, base_url: str = BASE_URL) -> None:
    """Fetch every missing file; a file whose hash does not match is discarded."""
    model_dir.mkdir(parents=True, exist_ok=True)
    for name, expected in MODEL_FILES.items():
        target = model_dir / name
        if target.is_file() and target.stat().st_size == expected.size:
            continue

        _LOGGER.info("Downloading %s (%.1f MB)", name, expected.size / 1e6)
        part = target.with_name(name + ".part")
        digest = hashlib.sha256()
        try:
            with urllib.request.urlopen(f"{base_url}/{name}", timeout=60) as response:
                with part.open("wb") as out:
                    while block := response.read(_CHUNK):
                        digest.update(block)
                        out.write(block)
            if digest.hexdigest() != expected.sha256:
                raise ValueError(
                    f"{name}: checksum mismatch, got {digest.hexdigest()}, "
                    f"expected {expected.sha256}. The file was discarded."
                )
            part.replace(target)
        finally:
            part.unlink(missing_ok=True)


def ensure_model(model_dir: Path) -> None:
    if model_installed(model_dir):
        _LOGGER.debug("Model found in %s", model_dir)
        return
    _LOGGER.info("Model not found in %s, downloading (~640 MB, one-time)", model_dir)
    download_model(model_dir)
    _LOGGER.info("Model downloaded and verified")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(sys.argv) != 2:
        sys.exit(f"usage: {sys.argv[0]} MODEL_DIR")
    target_dir = Path(sys.argv[1])
    download_model(target_dir)
    # Fail the build if anything is left over, e.g. a stray .part file.
    unexpected = {p.name for p in target_dir.iterdir()} - set(MODEL_FILES)
    if unexpected:
        sys.exit(f"unexpected files in {target_dir}: {sorted(unexpected)}")
    print(f"{len(MODEL_FILES)} files verified in {target_dir}")
