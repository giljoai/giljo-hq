# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from api.middleware import auth_rate_limiter as _arl


def test_real_auth_rate_limiter_pins_the_limiter_clock_to_a_window_start(real_auth_rate_limiter):
    first = _arl.time.time()
    second = _arl.time.time()

    assert first == second, "the limiter clock must not move inside a test"
    assert first % 60 == 0, "the pinned clock must sit at the start of a 60s window"


def test_a_test_can_still_roll_the_window_itself(real_auth_rate_limiter, monkeypatch):
    pinned = _arl.time.time()
    monkeypatch.setattr(_arl.time, "time", lambda: pinned + 60.0)

    assert _arl.time.time() == pinned + 60.0
