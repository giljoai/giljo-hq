# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import re
import unicodedata
from pathlib import PurePosixPath



TEXT_EXTENSIONS: frozenset[str] = frozenset({".txt", ".md", ".markdown"})

SNIFF_BYTES: int = 8192

MAX_FILENAME_BYTES: int = 255




class UploadFilenameError(ValueError):
    pass


class UploadContentError(ValueError):
    pass


class UploadSizeError(ValueError):
    pass



_BIDI_CHARS: frozenset[str] = frozenset(
    {
        "\u202a",
        "\u202b",
        "\u202c",
        "\u202d",
        "\u202e",
        "\u2066",
        "\u2067",
        "\u2068",
        "\u2069",
        "\u200e",
        "\u200f",
        "\u061c",
    }
)

_WINDOWS_RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$", re.IGNORECASE)

_WIN_ABS_PATH = re.compile(r"^[A-Za-z]:[\\/]")

_FORBIDDEN_CHARS: frozenset[str] = frozenset('<>:"|?*')


def _has_control_char(value: str) -> bool:
    for ch in value:
        code = ord(ch)
        if code < 0x20 or code == 0x7F:
            return True
    return False


def sanitize_upload_filename(raw: str | None) -> str:
    if raw is None or not raw or not raw.strip():
        raise UploadFilenameError("filename is empty")

    stripped = raw.strip()
    normalized = unicodedata.normalize("NFC", stripped)

    if _has_control_char(normalized):
        raise UploadFilenameError("filename contains control characters")

    if any(ch in _BIDI_CHARS for ch in normalized):
        raise UploadFilenameError("filename contains bidi/RTL override characters")

    if "/" in normalized or "\\" in normalized or "\x00" in normalized:
        raise UploadFilenameError("filename contains path separators")

    if ".." in normalized:
        raise UploadFilenameError("filename contains path traversal")

    if normalized.startswith("/") or _WIN_ABS_PATH.match(normalized):
        raise UploadFilenameError("filename is an absolute path")

    if any(ch in _FORBIDDEN_CHARS for ch in normalized):
        raise UploadFilenameError("filename contains forbidden characters")

    if normalized.startswith("."):
        raise UploadFilenameError("filename starts with a dot")

    if len(normalized.encode("utf-8")) > MAX_FILENAME_BYTES:
        raise UploadFilenameError("filename exceeds 255 bytes")

    stem = normalized.rsplit(".", 1)[0] if "." in normalized else normalized
    if _WINDOWS_RESERVED.match(stem):
        raise UploadFilenameError("filename uses a reserved device name")

    return PurePosixPath(normalized).name



_BINARY_BYTES: frozenset[int] = frozenset(set(range(0x09)) | {0x0B, 0x0C} | set(range(0x0E, 0x20)))


def is_text_content(content: bytes, *, sniff_bytes: int = SNIFF_BYTES) -> bool:
    window = content[:sniff_bytes]
    for byte in window:
        if byte in _BINARY_BYTES:
            return False

    try:
        content.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return False

    return True


def enforce_text_content(content: bytes, *, sniff_bytes: int = SNIFF_BYTES) -> None:
    if not is_text_content(content, sniff_bytes=sniff_bytes):
        raise UploadContentError("uploaded content does not look like plain UTF-8 text")
