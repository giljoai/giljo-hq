# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Collision-free taxonomy serials for tests that seed ``Project`` rows directly.

WHY THIS EXISTS (BE-9429). ``uq_project_taxonomy_active`` is UNIQUE over
``(tenant_key, product_id, project_type_id, series_number, subseries)`` with
**NULLS NOT DISTINCT**, partial on ``deleted_at IS NULL``. Under NULLS NOT
DISTINCT the NULL columns compare EQUAL, so two live rows that leave
``product_id`` / ``project_type_id`` / ``subseries`` NULL collide unless their
``series_number`` differs. A fixture that hardcodes ``series_number=1`` can
therefore seed exactly ONE project per database.

That constraint has always shipped -- every migration builds the index with
NULLS NOT DISTINCT -- but the model omitted the flag, so ``create_all`` built a
WEAKER index for the test schema and the collision was invisible in CI. BE-9429
fixed the model, which is what surfaced this.

WHY A PROCESS-GLOBAL COUNTER rather than a per-module one. Under pytest-xdist
every test file assigned to a worker shares that worker's ONE database, and
these rows outlive the test that created them. Two modules each counting from 1
would collide with each other, which is precisely the failure this replaces --
just moved. One counter per process is one counter per database, so the numbers
it hands out are unique everywhere they can meet.

NOT a random draw: ``test_statistics_service.py`` records that a
``random.randint`` serial was a latent flake for this exact reason. Monotonic
allocation cannot collide; a random one merely collides rarely.

Realism note: this mirrors what production does. A project created through
``ProjectService.create_project`` never carries a NULL serial -- the service
auto-assigns from the shared allocator (``get_next_series_number_shared``,
``project_service/_mutation_mixin.py:142-144``) when the caller supplies none.
Fixtures that construct ``Project(...)`` directly bypass that allocator, so they
have to do its job themselves.
"""

from __future__ import annotations

import itertools


# Starts above the small hand-written literals (1, 2, 3 ...) that fixtures and
# assertions elsewhere still use, so a seeded row can never occupy a number a
# test wrote by hand and expects to own.
_SERIES_COUNTER = itertools.count(1000)


def next_series_number() -> int:
    """Return a serial no other seeded project in this process will use.

    Use for any ``Project(...)`` built directly in a test. If the test asserts on
    a specific serial, pass that literal explicitly instead -- and give the row
    its own product so it cannot collide.
    """
    return next(_SERIES_COUNTER)
