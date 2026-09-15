# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from pathlib import Path

from cryptography.fernet import Fernet


logger = logging.getLogger(__name__)


SECRET_FILE_ATTEMPTS = 20
SECRET_FILE_RETRY_DELAY_SECONDS = 0.05


def is_valid_fernet_key(key: bytes) -> bool:
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
    secret_file.parent.mkdir(parents=True, exist_ok=True)

    for _ in range(SECRET_FILE_ATTEMPTS):
        try:
            binary = getattr(os, "O_BINARY", 0)
            fd = os.open(secret_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY | binary, 0o600)
        except FileExistsError:
            pass
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
