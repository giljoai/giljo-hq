# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from giljo_mcp import branding


class LicenseEdition(StrEnum):
    CE = "CE"


LicenseState = Literal["active", "read_only", "denied"]


@dataclass(frozen=True)
class LicenseResult:
    edition: LicenseEdition
    valid: bool
    seat_limit: int | None
    licensee: str | None
    message: str
    state: LicenseState = "active"


class LicenseValidator:

    def validate(self) -> LicenseResult:
        return LicenseResult(
            edition=LicenseEdition.CE,
            valid=True,
            seat_limit=None,
            licensee=None,
            message=f"{branding.PRODUCT_NAME} Community Edition — Elastic License 2.0.",
        )
