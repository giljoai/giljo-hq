# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9347 -- the log-archive filter must match what rotation actually writes.

Failing layer this regression-locks: ``api/endpoints/downloads/logs.py``. Its
``_ARCHIVE_PATTERN`` accepted only date-suffixed names
(``giljo_mcp.log.YYYY-MM-DD``), but every writer in the codebase is a size-based
``RotatingFileHandler`` subclass emitting NUMBERED suffixes (``giljo_mcp.log.1``
... ``.5``). So every archive the running system produces was invisible to the
listing endpoint that exists to serve it, and the download route rejected it with
400. Legacy date-named leftovers from an earlier configuration could still appear,
which is why the accurate claim is "every archive the current handlers produce is
invisible", not "the list is always empty".

``_ARCHIVE_PATTERN`` is ALSO the filename allowlist that stops ``{filename}``
being used for path traversal on the download route, so the traversal-rejection
tests here are load-bearing, not decorative -- they are what makes widening the
pattern safe.

Exercised at the API layer through the real ASGI transport and the real router,
which is the layer the defect lived at.

Edition Scope: CE. ``downloads.log_router`` is included by
``api/wiring/routers.py`` only when ``GILJO_MODE in ("", "ce")``, so these routes
do not exist in SaaS.

Parallel-safe: monkeypatched module constant + tmp_path only. No DB, no
module-level mutable state, no ordering dependency.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest


def _build_app(monkeypatch, log_dir):
    """A minimal app carrying the real ``log_router`` against a seeded log dir."""
    from fastapi import FastAPI

    from api.endpoints.downloads import logs as logs_mod
    from giljo_mcp.auth.dependencies import get_current_active_user

    monkeypatch.setattr(logs_mod, "_LOG_DIR", log_dir)

    app = FastAPI()
    app.include_router(logs_mod.log_router)
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(username="tester")
    return app


async def _get(app, path: str):
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


def _seed(log_dir, name: str, body: str = "rotated log content") -> None:
    (log_dir / name).write_text(body, encoding="utf-8")


def response_filenames(response) -> list[str]:
    return [entry["filename"] for entry in response.json()]


@pytest.mark.asyncio
async def test_listing_includes_size_rotated_archive(monkeypatch, tmp_path):
    """THE regression target: a numbered archive is what rotation writes, so it
    must be listed. RED before the fix -- the date-only pattern never matched it."""
    _seed(tmp_path, "giljo_mcp.log")  # the live file, never an archive
    _seed(tmp_path, "giljo_mcp.log.1")

    app = _build_app(monkeypatch, tmp_path)
    response = await _get(app, "/api/download/logs/archives")

    assert response.status_code == 200
    listed = {entry["filename"] for entry in response.json()}
    assert "giljo_mcp.log.1" in listed, f"size-rotated archive missing from listing: {listed}"


@pytest.mark.asyncio
async def test_listing_includes_multi_digit_rotation_index(monkeypatch, tmp_path):
    """``LoggingConfig.max_files`` is operator-configurable (default 5), so a
    self-hoster can legitimately produce ``giljo_mcp.log.12``. A single-digit
    pattern would be a fresh instance of the same defect."""
    _seed(tmp_path, "giljo_mcp.log.12")

    app = _build_app(monkeypatch, tmp_path)
    response = await _get(app, "/api/download/logs/archives")

    listed = {entry["filename"] for entry in response.json()}
    assert "giljo_mcp.log.12" in listed


@pytest.mark.asyncio
async def test_legacy_date_suffixed_archive_still_listed(monkeypatch, tmp_path):
    """Tolerate the old shape: date-named leftovers from an earlier configuration
    must not vanish from the list. This is the data-facing DoD answer -- no
    migration, the reader accepts both shapes."""
    _seed(tmp_path, "giljo_mcp.log.2026-04-12")

    app = _build_app(monkeypatch, tmp_path)
    response = await _get(app, "/api/download/logs/archives")

    listed = {entry["filename"] for entry in response.json()}
    assert "giljo_mcp.log.2026-04-12" in listed


@pytest.mark.asyncio
async def test_current_log_is_not_listed_as_an_archive(monkeypatch, tmp_path):
    """The live file has its own endpoint; widening must not sweep it into the
    archive list."""
    _seed(tmp_path, "giljo_mcp.log")

    app = _build_app(monkeypatch, tmp_path)

    assert response_filenames(await _get(app, "/api/download/logs/archives")) == []


@pytest.mark.asyncio
async def test_every_listed_archive_is_actually_downloadable(monkeypatch, tmp_path):
    """A file that appears in the list and then 400s is worse than not listing it.
    Walks the listing and fetches every entry end to end."""
    _seed(tmp_path, "giljo_mcp.log.1", "body of rotation one")
    _seed(tmp_path, "giljo_mcp.log.5", "body of rotation five")
    _seed(tmp_path, "giljo_mcp.log.2026-04-12", "body of the legacy archive")

    app = _build_app(monkeypatch, tmp_path)
    listing = await _get(app, "/api/download/logs/archives")
    filenames = response_filenames(listing)
    assert len(filenames) == 3, f"expected all three archives listed, got {filenames}"

    for filename in filenames:
        download = await _get(app, f"/api/download/logs/archive/{filename}")
        assert download.status_code == 200, f"listed but not downloadable: {filename} -> {download.status_code}"
        assert download.text == (tmp_path / filename).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_listing_reports_a_valid_date_and_rotation_index(monkeypatch, tmp_path):
    """The UI renders ``new Date(`${date}T00:00:00`)``, so a raw ``"1"`` suffix
    would print "Invalid Date" for every numbered archive. ``date`` must stay a
    real ISO date, and ``rotation_index`` is what keeps same-day rotations
    distinguishable."""
    _seed(tmp_path, "giljo_mcp.log.1")
    _seed(tmp_path, "giljo_mcp.log.2026-04-12")

    app = _build_app(monkeypatch, tmp_path)
    entries = {entry["filename"]: entry for entry in (await _get(app, "/api/download/logs/archives")).json()}

    numbered = entries["giljo_mcp.log.1"]
    assert numbered["rotation_index"] == 1
    # mtime-derived, but the shape is what the UI depends on
    assert len(numbered["date"]) == 10 and numbered["date"].count("-") == 2

    legacy = entries["giljo_mcp.log.2026-04-12"]
    assert legacy["date"] == "2026-04-12"
    assert legacy["rotation_index"] is None


@pytest.mark.asyncio
async def test_listing_is_ordered_newest_first(monkeypatch, tmp_path):
    """Numbered rotation counts UP as files get OLDER (``.1`` is the most recently
    rotated), which is the opposite of intuition -- so ascending index is
    newest-first. Legacy dated leftovers predate anything the current handler
    wrote, so they follow, newest date first."""
    for name in ("giljo_mcp.log.5", "giljo_mcp.log.1", "giljo_mcp.log.10", "giljo_mcp.log.2"):
        _seed(tmp_path, name)
    _seed(tmp_path, "giljo_mcp.log.2026-04-12")
    _seed(tmp_path, "giljo_mcp.log.2026-07-30")

    app = _build_app(monkeypatch, tmp_path)

    assert response_filenames(await _get(app, "/api/download/logs/archives")) == [
        "giljo_mcp.log.1",
        "giljo_mcp.log.2",
        "giljo_mcp.log.5",
        "giljo_mcp.log.10",
        "giljo_mcp.log.2026-07-30",
        "giljo_mcp.log.2026-04-12",
    ]


def _plant_canary(tmp_path) -> None:
    """Seed a real archive plus a secret one directory UP, where traversal lands."""
    _seed(tmp_path, "giljo_mcp.log")
    _seed(tmp_path, "giljo_mcp.log.1")
    (tmp_path.parent / ".env").write_text("SECRET=must-not-be-served", encoding="utf-8")


# Names that REACH the handler, so ``_ARCHIVE_PATTERN`` itself is what has to refuse
# them. The backslash entries are the ones that make this list load-bearing: on
# Windows -- the primary CE self-host platform -- ``%5C`` decodes to a real path
# separator, the router does NOT refuse it, and the allowlist is the only thing
# between it and the filesystem.
_REFUSED_BY_THE_ALLOWLIST = [
    "giljo_mcp.log.1%5C..%5C..%5C.env",
    "..%5C.env",
    "giljo_mcp.log.1%00.txt",
    "giljo_mcp.log",  # the live file -- has its own route, not fetchable here
    "giljo_mcp.log.",
    "giljo_mcp.log.0",  # rotation never writes .0
    "giljo_mcp.log.01",  # nor zero-padded indices
    "giljo_mcp.log.-1",
    "giljo_mcp.log.1.bak",
    "giljo_mcp.log.2026-04-12.gz",
    "giljo_mcp.log.abc",
    "GILJO_MCP.LOG.1",
    "giljo_mcp.log.1%0A",
    "giljo_mcp.log.2026-04-12%0A",
    # Arabic-Indic digits. The DATE form is the one that bites: ``\d`` matches any
    # Unicode digit while ``[0-9]`` does not, so this is what stops the pattern
    # drifting back to ``\d``. The single-digit form below cannot catch that (the
    # index branch opens with ASCII-only ``[1-9]`` either way) but pins the
    # look-alike class.
    "giljo_mcp.log.%D9%A1",
    "giljo_mcp.log.%D9%A2%D9%A0%D9%A2%D9%A6-%D9%A0%D9%A4-%D9%A1%D9%A2",
    # Separators as literal dots: if the ``\.`` in the pattern ever lose their
    # backslashes they become wildcards and this name is admitted.
    "giljo_mcpXlogX1",
]

# Refused by Starlette's ROUTER before the handler is ever called -- a ``/`` never
# matches a ``{filename}`` segment. Kept because the route must stay unreachable
# this way too, but they carry no signal about the allowlist: every one of them
# would behave identically if ``_ARCHIVE_PATTERN`` were deleted outright. That is
# why they are asserted separately and not counted as allowlist coverage.
_REFUSED_BY_THE_ROUTER = [
    "../.env",
    "../../.env",
    "..%2F..%2F.env",
    "giljo_mcp.log.1/../../../etc/passwd",
    "/etc/passwd",
]


@pytest.mark.parametrize("filename", _REFUSED_BY_THE_ALLOWLIST)
@pytest.mark.asyncio
async def test_traversal_and_non_archive_filenames_are_rejected(monkeypatch, tmp_path, filename):
    """The allowlist is the traversal guard on this route. Widening it must not
    admit a single name it previously refused, other than the numbered form.

    Asserts 400 specifically rather than "not 200": a 404 would mean the name got
    PAST ``_ARCHIVE_PATTERN`` and was stopped only by the file not happening to
    exist -- a coincidence, not a guard. That distinction is what makes this test
    fail when the pattern is loosened instead of quietly still passing.
    """
    _plant_canary(tmp_path)

    app = _build_app(monkeypatch, tmp_path)
    response = await _get(app, f"/api/download/logs/archive/{filename}")

    assert response.status_code == 400, f"allowlist did not refuse {filename!r} (got {response.status_code})"
    assert "must-not-be-served" not in response.text


@pytest.mark.parametrize("filename", _REFUSED_BY_THE_ROUTER)
@pytest.mark.asyncio
async def test_slash_bearing_filenames_never_reach_the_download_route(monkeypatch, tmp_path, filename):
    """Slash-bearing names are stopped one layer earlier, by the router.

    Asserted apart from the allowlist cases on purpose: these never invoke
    ``_ARCHIVE_PATTERN`` at all, so 404 here is the router doing its job and
    requiring 400 would be wrong.
    """
    _plant_canary(tmp_path)

    app = _build_app(monkeypatch, tmp_path)
    response = await _get(app, f"/api/download/logs/archive/{filename}")

    assert response.status_code != 200, f"route served {filename!r}"
    assert "must-not-be-served" not in response.text


@pytest.mark.parametrize("filename", ["giljo_mcp.log.1%0A", "giljo_mcp.log.2026-04-12%0A"])
@pytest.mark.asyncio
async def test_trailing_newline_is_refused_by_the_allowlist_not_merely_missing(monkeypatch, tmp_path, filename):
    """Anchor precision, pinned separately because a 404 would mask it.

    Python's ``$`` also matches just before a trailing newline, so
    ``giljo_mcp.log.2026-04-12\\n`` got PAST the old allowlist and was refused only
    by the file-existence check (404). The allowlist itself must refuse it (400) --
    that is the difference between a guard and a coincidence. ``\\Z`` is what makes
    it so.
    """
    _seed(tmp_path, "giljo_mcp.log.1")
    _seed(tmp_path, "giljo_mcp.log.2026-04-12")

    app = _build_app(monkeypatch, tmp_path)
    response = await _get(app, f"/api/download/logs/archive/{filename}")

    assert response.status_code == 400, f"{filename!r} should be refused by the allowlist, got {response.status_code}"


@pytest.mark.asyncio
async def test_directory_named_like_an_archive_is_not_served(monkeypatch, tmp_path):
    """A directory matching the pattern would otherwise be listed and then fail
    inside FileResponse."""
    (tmp_path / "giljo_mcp.log.3").mkdir()

    app = _build_app(monkeypatch, tmp_path)

    assert response_filenames(await _get(app, "/api/download/logs/archives")) == []
    assert (await _get(app, "/api/download/logs/archive/giljo_mcp.log.3")).status_code == 404


@pytest.mark.asyncio
async def test_archive_vanishing_mid_listing_does_not_500(monkeypatch, tmp_path):
    """Rotation renames these files underneath the listing. An archive that
    disappears between iterdir() and stat() must drop out of the results, not
    take the whole endpoint down -- opening the log menu while the server
    rotates is ordinary use, not an edge case."""
    from pathlib import Path

    _seed(tmp_path, "giljo_mcp.log.1")
    _seed(tmp_path, "giljo_mcp.log.2")

    real_stat = Path.stat

    def vanishing_stat(self, *args, **kwargs):
        if self.name == "giljo_mcp.log.1":
            raise FileNotFoundError(2, "No such file or directory", str(self))
        return real_stat(self, *args, **kwargs)

    app = _build_app(monkeypatch, tmp_path)
    monkeypatch.setattr(Path, "stat", vanishing_stat)
    response = await _get(app, "/api/download/logs/archives")

    assert response.status_code == 200
    assert response_filenames(response) == ["giljo_mcp.log.2"]


@pytest.mark.asyncio
async def test_missing_log_dir_lists_empty_rather_than_erroring(monkeypatch, tmp_path):
    """A fresh install has no logs/ directory yet."""
    app = _build_app(monkeypatch, tmp_path / "does-not-exist")
    response = await _get(app, "/api/download/logs/archives")

    assert response.status_code == 200
    assert response.json() == []
