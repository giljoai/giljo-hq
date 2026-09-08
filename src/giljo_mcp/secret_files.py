# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Crash-safe get-or-create for secrets that live in a shared file (SEC-9572).

Several processes routinely reach the same secret file at once -- ``uvicorn
--workers N`` boots N of them against one home directory -- so the obvious
exists()/read()/write() sequence is wrong in two ways at once: a reader can see
a file a writer created but has not yet filled, and two writers can both decide
the file is missing and race to define it.

Lifted here by SEC-9574 so the CE auth manager and the SaaS secrets manager
share one implementation instead of two that drift.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from pathlib import Path

from cryptography.fernet import Fernet


logger = logging.getLogger(__name__)


# How long a process that lost the create race will wait for the winner's bytes
# to appear before giving up. The observed window is sub-millisecond; this is
# generous by three orders of magnitude on purpose.
SECRET_FILE_ATTEMPTS = 20
SECRET_FILE_RETRY_DELAY_SECONDS = 0.05


def is_valid_fernet_key(key: bytes) -> bool:
    """True when ``key`` is 32 url-safe base64-encoded bytes, as Fernet requires."""
    try:
        Fernet(key)
    except (ValueError, TypeError):
        return False
    return True


def claim_or_read_secret_file(
    secret_file: Path,
    *,
    generate: Callable[[], bytes],
    is_valid: Callable[[bytes], bool],
    description: str,
) -> bytes:
    """Read a shared on-disk secret, creating it exactly once across processes.

    ``uvicorn --workers N`` boots N processes against one home directory, so a
    reader can otherwise observe a file the creator has not yet filled, yielding
    an unusable secret (SEC-9572).

    ``O_CREAT | O_EXCL`` makes exactly one process the creator, so every process
    converges on the SAME secret instead of on whichever write happened to land
    last. A process that loses the claim re-reads until the winner's bytes are
    visible, and only a file that stays unreadable raises -- naming itself.
    """
    secret_file.parent.mkdir(parents=True, exist_ok=True)

    for _ in range(SECRET_FILE_ATTEMPTS):
        try:
            # O_BINARY only exists on Windows, where os.open would otherwise
            # open in text mode and translate newlines on the way out.
            binary = getattr(os, "O_BINARY", 0)
            fd = os.open(secret_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY | binary, 0o600)
        except FileExistsError:
            pass  # Another process is the creator; read what it wrote.
        else:
            secret = generate()
            with os.fdopen(fd, "wb") as handle:
                handle.write(secret)
            logger.info("Generated new %s stored at: %s", description, secret_file)
            return secret

        existing = secret_file.read_bytes()
        if is_valid(existing):
            return existing
        time.sleep(SECRET_FILE_RETRY_DELAY_SECONDS)

    raise RuntimeError(
        f"The {description} at {secret_file} exists but does not hold a usable "
        f"value after {SECRET_FILE_ATTEMPTS} attempts. Delete the file to have "
        "Giljo HQ generate a new one (any API keys encrypted with the old value "
        "become unreadable), or restore it from a backup."
    )
