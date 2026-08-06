# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
License validation module.

Community Edition: always returns CE mode. No enforcement.

Commercial builds replace this module with a cryptographic key validator
that verifies a signed license file at startup. The interface contract
(LicenseResult dataclass + LicenseValidator.validate()) is stable and
must not change in CE without a corresponding update in the commercial build.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from giljo_mcp import branding


class LicenseEdition(StrEnum):
    CE = "CE"
    # [CE] Commercial editions declared here in the commercial build.
    # Do not add values to this enum in CE.


# Runtime license state. Drives the SaaS LicenseEnforcementMiddleware; CE
# always emits "active". Additive field — not part of the original CE contract,
# so SaaS subclasses can populate it without breaking commercial consumers.
LicenseState = Literal["active", "read_only", "denied"]


@dataclass(frozen=True)
class LicenseResult:
    edition: LicenseEdition
    valid: bool
    seat_limit: int | None  # None = unlimited (CE)
    licensee: str | None  # None = CE (no licensee)
    message: str
    state: LicenseState = "active"


class LicenseValidator:
    """
    Validates the runtime license.

    CE behavior: always returns a valid CE result. No file I/O, no network
    calls, no cryptographic checks. This is intentional.

    Commercial behavior (private repo): reads a signed license file,
    verifies the Ed25519 signature against the embedded public key,
    extracts seat count and expiry, returns the appropriate LicenseResult.
    The commercial build overrides this class entirely — it does not
    subclass it. The interface contract is the only shared surface.
    """

    def validate(self) -> LicenseResult:
        # [CE] CE always returns valid CE mode. Do not modify this return value.
        # Commercial builds replace this method with cryptographic validation.
        # Under Elastic License 2.0 there is no per-user gate; seat_limit=None
        # signals "unlimited within the bounds of the ELv2 restrictions"
        # (no managed-service redistribution, no license-key tampering, no
        # notice removal).
        return LicenseResult(
            edition=LicenseEdition.CE,
            valid=True,
            seat_limit=None,
            licensee=None,
            message=f"{branding.PRODUCT_NAME} Community Edition — Elastic License 2.0.",
        )
