# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import base64
import hashlib
import re
from pathlib import Path

import pytest

from api.middleware.security import (
    CSP_SCRIPT_HASH_1,
    CSP_SCRIPT_HASH_2,
)


_INLINE_STYLE_RE = re.compile(r"<style\b", re.IGNORECASE)


def _find_index_html() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "frontend" / "index.html"
        if candidate.exists():
            return candidate
    return None


def _csp_hash(content: str) -> str:
    digest = hashlib.sha256(content.encode("utf-8")).digest()
    return f"'sha256-{base64.b64encode(digest).decode('utf-8')}'"


def _extract_inline_hashes(html: str) -> tuple[set[str], set[str]]:
    style_hashes = {_csp_hash(m.group(1)) for m in re.finditer(r"<style>(.*?)</style>", html, re.DOTALL)}
    script_hashes = {
        _csp_hash(m.group(1)) for m in re.finditer(r"<script(?![^>]*\bsrc=)(?:[^>]*)>(.*?)</script>", html, re.DOTALL)
    }
    return style_hashes, script_hashes


def _find_dist_index_html() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "frontend" / "dist" / "index.html"
        if candidate.exists():
            return candidate
    return None


def test_csp_inline_hashes_match_index_html() -> None:
    index_html = _find_index_html()
    if index_html is None:
        pytest.skip("frontend/index.html not present in this checkout")

    style_hashes, script_hashes = _extract_inline_hashes(index_html.read_text(encoding="utf-8"))

    shipped_scripts = {CSP_SCRIPT_HASH_1, CSP_SCRIPT_HASH_2}
    assert script_hashes == shipped_scripts, (
        "CSP script-src hashes in api/middleware/security.py are out of sync "
        "with the inline <script> blocks in frontend/index.html.\n"
        f"  index.html requires: {sorted(script_hashes)}\n"
        f"  security.py ships:   {sorted(shipped_scripts)}\n"
        "Run `python scripts/generate_csp_hashes.py` and update "
        "CSP_SCRIPT_HASH_1 / CSP_SCRIPT_HASH_2."
    )

    assert not style_hashes and not _INLINE_STYLE_RE.search(index_html.read_text(encoding="utf-8")), (
        "frontend/index.html carries an inline <style> block. Inline styles need a "
        "CSP hash that breaks whenever the build minifies them (FE-9676). Put the "
        "CSS in a stylesheet under frontend/public/ and link it instead."
    )


def test_csp_inline_hashes_match_dist_index_html() -> None:
    dist_html = _find_dist_index_html()
    if dist_html is None:
        pytest.skip("frontend/dist/index.html not present — run `npm run build` first")

    dist_text = dist_html.read_text(encoding="utf-8")

    if '<div id="app"' not in dist_text:
        pytest.skip(
            reason="frontend/dist/index.html is a CI placeholder, not a real Vite build "
            "— the built-artifact CSP guard only runs against a genuine `npm run build`"
        )

    style_hashes, script_hashes = _extract_inline_hashes(dist_text)

    shipped_scripts = {CSP_SCRIPT_HASH_1, CSP_SCRIPT_HASH_2}
    assert script_hashes == shipped_scripts, (
        "CSP script-src hashes in api/middleware/security.py are out of sync "
        "with the inline <script> blocks in frontend/dist/index.html (built artifact).\n"
        f"  dist/index.html requires: {sorted(script_hashes)}\n"
        f"  security.py ships:        {sorted(shipped_scripts)}\n"
        "The Vite build may have transformed the inline scripts. "
        "Run `python scripts/generate_csp_hashes.py` against the built dist/ and "
        "update CSP_SCRIPT_HASH_1 / CSP_SCRIPT_HASH_2 in api/middleware/security.py."
    )

    assert not style_hashes and not _INLINE_STYLE_RE.search(dist_text), (
        "frontend/dist/index.html (built artifact) carries an inline <style> block, "
        "which the CSP would block in SaaS (FE-9676). Keep the splash CSS in "
        "frontend/public/splash.css."
    )
    assert '<link rel="stylesheet" href="/splash.css">' in dist_text, (
        "frontend/dist/index.html no longer links /splash.css; the start-up splash would render unstyled."
    )
