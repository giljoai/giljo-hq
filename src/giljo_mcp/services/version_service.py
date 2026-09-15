# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
import time
from dataclasses import dataclass, field
from datetime import UTC
from pathlib import Path

import httpx


logger = logging.getLogger(__name__)

GITHUB_RELEASES_URL = "https://api.github.com/repos/giljoai/giljo-hq/releases/latest"
CACHE_TTL_SECONDS = 3600
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


@dataclass
class VersionInfo:

    installed_version: str
    latest_version: str | None = None
    latest_tarball_url: str | None = None
    latest_sha256: str | None = None
    update_available: bool = False
    checked_at: str | None = None


@dataclass
class _CacheEntry:

    data: VersionInfo
    fetched_at: float = field(default_factory=time.monotonic)


_cache_store: dict[str, _CacheEntry] = {}


def get_installed_version(root: Path | None = None) -> str:
    version_path = (root or PROJECT_ROOT) / "VERSION"
    try:
        return version_path.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError):
        logger.warning("VERSION file not found at %s", version_path)
        return "unknown"


def _parse_version_tuple(version_str: str) -> tuple[int, ...] | None:
    try:
        return tuple(int(p) for p in version_str.split("."))
    except (ValueError, AttributeError):
        return None


def compare_versions(installed: str, latest: str) -> bool:
    inst = _parse_version_tuple(installed)
    lat = _parse_version_tuple(latest)
    if inst is None or lat is None:
        return False
    return lat > inst


async def _fetch_latest_from_github(
    client: httpx.AsyncClient | None = None,
) -> tuple[str | None, str | None, str | None]:
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=10.0)
    try:
        resp = await client.get(
            GITHUB_RELEASES_URL,
            headers={"Accept": "application/vnd.github+json"},
        )
        if resp.status_code == 404:
            logger.info("No releases found on GitHub (404)")
            return None, None, None
        if resp.status_code == 403:
            logger.warning("GitHub API rate limit likely exceeded (403)")
            return None, None, None
        resp.raise_for_status()
        data = resp.json()

        tag = data.get("tag_name", "")
        version = tag.lstrip("v") if tag else None

        tarball_url = None
        sha256 = None

        assets = data.get("assets", [])
        manifest_asset = None
        for asset in assets:
            name = asset.get("name", "")
            if name.endswith(".tar.gz"):
                tarball_url = asset.get("browser_download_url")
            if name == "version-manifest.json":
                manifest_asset = asset

        if manifest_asset:
            manifest_url = manifest_asset.get("browser_download_url")
            if manifest_url:
                try:
                    manifest_resp = await client.get(manifest_url)
                    manifest_resp.raise_for_status()
                    manifest_data = manifest_resp.json()
                    if manifest_data.get("tarball_url"):
                        tarball_url = manifest_data["tarball_url"]
                    if manifest_data.get("sha256"):
                        sha256 = manifest_data["sha256"]
                except (httpx.HTTPError, ValueError, KeyError) as exc:
                    logger.warning("Failed to parse version-manifest.json: %s", exc)

        return version, tarball_url, sha256

    except httpx.HTTPError as exc:
        logger.warning("GitHub API request failed: %s", exc)
        return None, None, None
    finally:
        if own_client:
            await client.aclose()


async def get_version_info(
    root: Path | None = None,
    client: httpx.AsyncClient | None = None,
    _now: float | None = None,
) -> VersionInfo:
    installed = get_installed_version(root)
    now = _now if _now is not None else time.monotonic()

    entry = _cache_store.get("latest")
    if entry is not None and (now - entry.fetched_at) < CACHE_TTL_SECONDS:
        cached = entry.data
        return VersionInfo(
            installed_version=installed,
            latest_version=cached.latest_version,
            latest_tarball_url=cached.latest_tarball_url,
            latest_sha256=cached.latest_sha256,
            update_available=compare_versions(installed, cached.latest_version) if cached.latest_version else False,
            checked_at=cached.checked_at,
        )

    version, tarball_url, sha256 = await _fetch_latest_from_github(client)

    from datetime import datetime

    checked_at = datetime.now(UTC).isoformat()

    update_available = compare_versions(installed, version) if version else False

    info = VersionInfo(
        installed_version=installed,
        latest_version=version,
        latest_tarball_url=tarball_url,
        latest_sha256=sha256,
        update_available=update_available,
        checked_at=checked_at,
    )

    _cache_store["latest"] = _CacheEntry(data=info, fetched_at=now)
    return info


def clear_cache() -> None:
    _cache_store.clear()
