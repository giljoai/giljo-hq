# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import asyncio

import bcrypt


BCRYPT_MAX_PASSWORD_BYTES = 72

DUMMY_BCRYPT_HASH = "$2b$12$U9PdoxNs9zNrCo7Rf9red.G0bl3ZSv8BPF/mwaInIqe/H6AJ.AZKO"


async def async_hash_password(plaintext: str) -> str:
    hashed = await asyncio.to_thread(bcrypt.hashpw, plaintext.encode("utf-8"), bcrypt.gensalt(rounds=12))
    return hashed.decode("utf-8")


async def async_verify_password(plaintext: str, password_hash: str) -> bool:
    plaintext_bytes = plaintext.encode("utf-8")
    if len(plaintext_bytes) > BCRYPT_MAX_PASSWORD_BYTES:
        return False
    try:
        return await asyncio.to_thread(bcrypt.checkpw, plaintext_bytes, password_hash.encode("utf-8"))
    except ValueError:
        return False
