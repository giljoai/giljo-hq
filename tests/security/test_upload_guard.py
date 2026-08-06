# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
SEC-0001 Phase 2 -- unit tests for the upload guard helper module.

Covers the two pure helpers that back both upload endpoints:

- ``sanitize_upload_filename(raw)`` -- strict filename sanitizer that rejects
  directory separators, absolute paths, null bytes, C0/DEL control chars,
  Unicode bidi/RTL overrides, leading dots, Windows-reserved chars and
  device names, and anything whose UTF-8 byte length exceeds 255 bytes after
  NFC normalization.
- ``enforce_text_content(content)`` -- byte-sniff that rejects any payload
  containing C0 binary bytes (everything in ``[0x00, 0x20)`` except ``\\t``,
  ``\\n``, ``\\r``) within the first 8 KB, then requires a strict UTF-8
  decode of the whole payload.

These tests are the authoritative behavior spec in combination with the
analyzer handover for SEC-0001 upload analysis, sections 2 and 3.
Integration tests live in ``tests/api/test_sec_0001_upload_endpoints.py``.
"""

from __future__ import annotations

import pytest

from giljo_mcp.security.upload_guard import (
    TEXT_EXTENSIONS,
    UploadContentError,
    UploadFilenameError,
    enforce_text_content,
    is_text_content,
    sanitize_upload_filename,
)


# ---------------------------------------------------------------------------
# sanitize_upload_filename -- reject cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        "\t\n",
    ],
)
def test_sanitize_rejects_empty_or_whitespace(raw):
    with pytest.raises(UploadFilenameError):
        sanitize_upload_filename(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "../../etc/passwd",
        "..\\..\\windows\\system32",
        "foo/bar.txt",
        "foo\\bar.txt",
        "file\x00.txt",
        "..",
        "file..name.txt",  # contains traversal substring
    ],
)
def test_sanitize_rejects_path_traversal_and_separators(raw):
    with pytest.raises(UploadFilenameError):
        sanitize_upload_filename(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "/etc/passwd",
        "C:\\Windows\\boot.ini",
        "D:/secret.txt",
        "z:\\evil.md",
    ],
)
def test_sanitize_rejects_absolute_paths(raw):
    with pytest.raises(UploadFilenameError):
        sanitize_upload_filename(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "file\x01.txt",
        "file\x1f.txt",
        "file\x7f.txt",
        "\x08leading-bs.txt",
    ],
)
def test_sanitize_rejects_control_chars(raw):
    with pytest.raises(UploadFilenameError):
        sanitize_upload_filename(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "report\u202emoofdp.txt",  # U+202E RIGHT-TO-LEFT OVERRIDE
        "spoof\u202atxt.exe",  # U+202A LEFT-TO-RIGHT EMBEDDING
        "\u200espoof.txt",  # U+200E LEFT-TO-RIGHT MARK
        "\u2066bad.txt",  # U+2066 LEFT-TO-RIGHT ISOLATE
    ],
)
def test_sanitize_rejects_bidi_overrides(raw):
    with pytest.raises(UploadFilenameError):
        sanitize_upload_filename(raw)


def test_sanitize_rejects_leading_dot():
    with pytest.raises(UploadFilenameError):
        sanitize_upload_filename(".hidden")


def test_sanitize_rejects_leading_dot_after_strip():
    with pytest.raises(UploadFilenameError):
        sanitize_upload_filename("   .hidden")


def test_sanitize_rejects_overlength_bytes():
    raw = ("a" * 300) + ".txt"
    with pytest.raises(UploadFilenameError):
        sanitize_upload_filename(raw)


def test_sanitize_rejects_overlength_bytes_multibyte():
    # Each CJK char is 3 bytes UTF-8; 100 chars = 300 bytes > 255
    raw = ("文" * 100) + ".txt"
    with pytest.raises(UploadFilenameError):
        sanitize_upload_filename(raw)


@pytest.mark.parametrize(
    "stem",
    [
        "CON",
        "con",
        "PRN",
        "AUX",
        "NUL",
        "COM1",
        "COM9",
        "LPT1",
        "LPT9",
    ],
)
def test_sanitize_rejects_windows_reserved_device_names(stem):
    with pytest.raises(UploadFilenameError):
        sanitize_upload_filename(f"{stem}.txt")


@pytest.mark.parametrize(
    "raw",
    [
        "file<.txt",
        "file>.txt",
        'file".txt',
        "file|pipe.txt",
        "file?.txt",
        "file*.txt",
        "file:stream.txt",
    ],
)
def test_sanitize_rejects_windows_forbidden_chars(raw):
    with pytest.raises(UploadFilenameError):
        sanitize_upload_filename(raw)


# ---------------------------------------------------------------------------
# sanitize_upload_filename -- accept cases
# ---------------------------------------------------------------------------


def test_sanitize_accepts_plain_txt():
    assert sanitize_upload_filename("valid-doc.md") == "valid-doc.md"


def test_sanitize_accepts_dashes_and_digits():
    assert sanitize_upload_filename("2026-04-roadmap.md") == "2026-04-roadmap.md"


def test_sanitize_accepts_umlauts_via_nfc():
    # NFC normalization: both composed and decomposed "ü" produce the same result
    composed = "über.md"
    decomposed = "über.md"
    result_composed = sanitize_upload_filename(composed)
    result_decomposed = sanitize_upload_filename(decomposed)
    assert result_composed == result_decomposed
    assert result_composed == "über.md"


def test_sanitize_accepts_cjk():
    assert sanitize_upload_filename("文档.md") == "文档.md"


def test_sanitize_strips_outer_whitespace():
    assert sanitize_upload_filename("  report.txt  ") == "report.txt"


def test_sanitize_returns_basename_when_dir_like_input_is_safe():
    # Any input with "/" or "\\" is rejected by the traversal rule before
    # reaching the defense-in-depth basename step. Verify a no-sep name stays
    # equal to itself.
    assert sanitize_upload_filename("filename.txt") == "filename.txt"


def test_sanitize_markdown_extension_allowed_by_sanitizer():
    # Sanitizer itself does NOT enforce extension allowlist; that is a separate
    # guard in the endpoint. It should NOT reject valid .markdown names.
    assert sanitize_upload_filename("notes.markdown") == "notes.markdown"


# ---------------------------------------------------------------------------
# TEXT_EXTENSIONS contract
# ---------------------------------------------------------------------------


def test_text_extensions_set_values():
    assert frozenset({".txt", ".md", ".markdown"}) == TEXT_EXTENSIONS


def test_text_extensions_is_immutable():
    # frozenset guards the allowlist against accidental mutation at runtime
    assert isinstance(TEXT_EXTENSIONS, frozenset)


# ---------------------------------------------------------------------------
# is_text_content / enforce_text_content -- reject binary magic
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "label"),
    [
        # Real PDFs always have a binary-byte comment on line 2 (per ISO 32000
        # convention) plus non-UTF-8 byte runs in xref/stream bodies. Model
        # both here so the sniff triggers on either the binary window or the
        # strict UTF-8 decode step.
        (b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<\n/Type /Catalog\n>>", "PDF"),
        (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR", "PNG"),
        (b"PK\x03\x04\x14\x00\x08", "ZIP/DOCX"),
        (b"\xff\xd8\xff\xe0\x00\x10JFIF", "JPEG"),
        (b"\x7fELF\x02\x01\x01\x00", "ELF"),
        (b"\x1f\x8b\x08\x00", "GZIP"),
        (b"\x00\x00\x00\x0cJXL \r\n", "JPEG XL (null leader)"),
        (b"\xff\xfe\x68\x00\x65\x00", "UTF-16 LE BOM + text"),
    ],
)
def test_is_text_content_rejects_binary_magic(payload, label):
    assert is_text_content(payload) is False, f"expected {label} to be rejected"


def test_enforce_text_content_raises_on_binary():
    # NUL byte in the sniff window triggers the binary-byte guard.
    with pytest.raises(UploadContentError):
        enforce_text_content(b"%PDF-1.4\n\x00binary")


def test_enforce_text_content_raises_on_pdf_header():
    # Real PDF header with binary marker + non-UTF-8 bytes.
    payload = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\nbody"
    with pytest.raises(UploadContentError):
        enforce_text_content(payload)


def test_enforce_text_content_raises_on_invalid_utf8():
    # Valid ASCII-range bytes only, but one invalid UTF-8 continuation
    # Use a byte that passes the binary-byte sniff but fails strict UTF-8
    payload = b"hello " + b"\xff" + b" world"
    with pytest.raises(UploadContentError):
        enforce_text_content(payload)


# ---------------------------------------------------------------------------
# is_text_content / enforce_text_content -- accept plain text
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "label"),
    [
        (b"hello world", "ASCII"),
        (b"hello\ttabbed\nnewlined\r\n", "ASCII with \\t\\n\\r"),
        (b"\xef\xbb\xbfhello", "UTF-8 BOM + ASCII"),
        ("文档 notes".encode(), "CJK UTF-8"),
        (b"# Heading\n\nParagraph with _markdown_.\n", "Markdown"),
        (b"", "empty file"),
    ],
)
def test_is_text_content_accepts_plain_text(payload, label):
    assert is_text_content(payload) is True, f"expected {label} to be accepted"


def test_enforce_text_content_noop_on_valid_text():
    # Should not raise
    enforce_text_content(b"# SEC-0001\n\nClean text.\n")


def test_is_text_content_inspects_only_sniff_window():
    # A 16 KB payload whose first 8 KB is clean ASCII, followed by binary.
    # Strict UTF-8 decode covers the whole payload so this is still rejected,
    # but the reason should be UTF-8 failure, not the sniff window.
    head = b"a" * 8192
    tail = b"\xff\xfe" * 4096  # Invalid UTF-8 tail
    assert is_text_content(head + tail) is False


def test_is_text_content_accepts_large_clean_text():
    payload = b"a" * 50000
    assert is_text_content(payload) is True
