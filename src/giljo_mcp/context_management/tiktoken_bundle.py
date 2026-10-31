# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import gzip
import hashlib
import logging
import os
import tempfile
from pathlib import Path


logger = logging.getLogger(__name__)

BUNDLED_DIR = Path(__file__).parent / "tiktoken_cache"

BUNDLED_ENCODINGS = {
    "9b5ad71b2ce5302211f9c61530b329a4922fc6a4": "223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7",
    "fb374d419588a4632f3f557e76b4b70aebbca790": "446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d",
}


def _candidate_cache_dirs() -> list[Path]:
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        base = Path(os.environ["LOCALAPPDATA"])
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return [base / "giljo_hq" / "tiktoken", Path(tempfile.gettempdir()) / "giljo_hq_tiktoken"]


def _unpack(name: str, expected_sha256: str, target_dir: Path) -> None:
    target = target_dir / name
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == expected_sha256:
        return
    data = gzip.decompress((BUNDLED_DIR / f"{name}.gz").read_bytes())
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValueError(f"Bundled tiktoken encoding {name} failed its sha256 check")
    fd, tmp_name = tempfile.mkstemp(dir=target_dir, prefix=f".{name}.")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        Path(tmp_name).replace(target)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def use_bundled_tiktoken_cache() -> None:
    if "TIKTOKEN_CACHE_DIR" in os.environ:
        return
    last_error: OSError | None = None
    for cache_dir in _candidate_cache_dirs():
        try:
            cache_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
            for name, sha256 in BUNDLED_ENCODINGS.items():
                _unpack(name, sha256, cache_dir)
        except OSError as exc:
            last_error = exc
            continue
        os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(cache_dir))
        return
    logger.warning(
        "No writable cache directory for the bundled tiktoken encodings; tiktoken will download them: %s",
        last_error,
    )
