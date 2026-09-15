# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

from giljo_mcp.licensing import LicenseResult, LicenseValidator
from giljo_mcp.licensing.validator import LicenseEdition


def test_ce_validator_returns_valid_result():
    result = LicenseValidator().validate()
    assert isinstance(result, LicenseResult)
    assert result.valid is True


def test_ce_validator_returns_ce_edition():
    result = LicenseValidator().validate()
    assert result.edition == LicenseEdition.CE


def test_ce_validator_has_no_seat_limit_under_elv2():
    result = LicenseValidator().validate()
    assert result.seat_limit is None


def test_ce_validator_has_no_licensee():
    result = LicenseValidator().validate()
    assert result.licensee is None


def test_ce_validator_message_is_present():
    result = LicenseValidator().validate()
    assert isinstance(result.message, str)
    assert len(result.message) > 0
