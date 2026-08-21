# Migrations

This directory holds the Alembic migration chains for the Giljo HQ database.

## Layout

- `versions/` — **CE migration chain.** All CE schema lives here. `startup.py` runs `alembic upgrade head` against this chain on every boot.
- `saas_versions/` — **SaaS migration chain.** Only loaded when `GILJO_MODE=saas`. Reserved for SaaS-only tables (`tenants`, `password_reset_tokens`, etc.).
- `archive/` — pre-baseline history, kept for reference only. Not executed.
- `manual/` — one-off manual SQL scripts (data fixes, repair operations). Not part of any chain.
- `revision_registry.json` — tracks revision IDs to avoid collisions.

## Chain topology after the v38 squash (INF-5060)

The CE chain is `baseline_v37 → ce_0001 … ce_0077 → baseline_v38`, where
**`baseline_v38` is a guarded full-schema TIP, not a second root** (the
alembic "squash as guarded tip" pattern). One graph, one head, and every
historical revision ID stays resolvable. How each database state flows:

- **Fresh install:** the installer/boot seams (`installer/core/database_setup.py`,
  `startup_support/migration_stamp.py`) detect a DB with no `alembic_version`
  table, create it at VARCHAR(64), and stamp the squash boundary (`ce_0077…`).
  `alembic upgrade head` then executes ONLY `baseline_v38` — one baseline
  instead of a 77-migration replay.
- **Existing mid-chain DB:** upgrades through the REAL incremental chain (all
  data backfills run), then `baseline_v38`'s existence guards no-op.
- **At-head DB (SaaS prod's `alembic upgrade heads`, staging, dev):**
  `baseline_v38` runs as a pure no-op.

**Parity invariant (enforced by
`tests/integration/migrations/test_inf5060_squash_baseline_v38.py`):** the
schema built by the fresh fast path is IDENTICAL — column order, types,
nullability, server defaults, indexes, constraints, comments — to the schema
built by replaying the chain. If you edit `baseline_v38_unified.py`, you must
keep that invariant: pair any baseline edit with the matching incremental
migration (or ship the change only in the baseline while it is genuinely
unshipped, per the routing tree below).

**Future squashes repeat this pattern:** author `baseline_v39` as the new
guarded tip, move the fresh-install stamp boundary forward in BOTH seams
(`FRESH_INSTALL_STAMP_REVISION` in `startup_support/migration_stamp.py` +
the literal in `installer/core/database_setup.py`), and keep the three
copies in sync (pinned by the `test_squash_boundary_revision_in_sync` test).

## Routing decision tree (run this first)

Before adding ANY migration, decide which chain it belongs in:

```
Is the table SaaS-only (defined under saas/ models)?
├── YES → migrations/saas_versions/  (will only run with GILJO_MODE=saas)
└── NO (table is a CE model, even if SaaS extends it)
    │
    Is this a column / index / constraint change on an existing CE table?
    ├── YES → migrations/versions/  (incremental migration, MUST be idempotent)
    └── NO — it's a brand-new table for an unreleased feature
        │
        Has the feature shipped to ANY environment (test install, demo prod, public)?
        ├── YES → migrations/versions/  (incremental — existing DBs need ALTER)
        └── NO  → modify the baseline (baseline_v38_unified.py)
```

**Why the split:**
- **Baseline** (`baseline_v38_unified.py`) creates all tables in one shot for fresh installs. Fast (<1 second), zero historical baggage. Only safe to modify for tables/columns that don't yet exist in ANY running database.
- **Incremental migrations** in `versions/` are how existing databases (any self-hosted CE install, including upgraded ones) get schema updates. Once a feature ships, the baseline can no longer be the only source of truth — running installs need an ALTER path.

## Hard rules

1. **CE columns → CE chain.** A column added to any model under `src/giljo_mcp/models/` (outside `saas/`) MUST have its migration in `versions/`, never `saas_versions/`. Mis-routing crashes CE deploys with "column does not exist" because SQLAlchemy SELECTs all model columns at query time and `startup.py` only runs the CE chain.

2. **Incremental migrations must be idempotent.** Wrap with existence checks so a re-run doesn't crash:
   ```python
   from sqlalchemy import inspect

   def upgrade():
       bind = op.get_bind()
       inspector = inspect(bind)
       columns = [c["name"] for c in inspector.get_columns("my_table")]
       if "my_new_column" not in columns:
           op.add_column("my_table", sa.Column("my_new_column", sa.String(), nullable=True))
   ```
   Same pattern for tables, indexes, constraints. The CE installer reruns migrations on every boot — non-idempotent migrations break users.

3. **Tenant-key columns are mandatory** on every new domain table. CE uses `tenant_key` (single-tenant), SaaS uses `tenant_key` (multi-tenant org-scoped). Never add a domain table without it.

4. **alembic.ini is in the protected zone.** You should rarely need to edit it — adding a migration file does NOT require alembic.ini changes. If you genuinely need to (e.g., changing `script_location` or adding a branch label), stop and ask for one-time approval per the Protected Zones rule in CLAUDE.md.

5. **Writes during a migration bypass the service layer by design.** The "all product writes go through ProductService" rule (CLAUDE.md, post-0962) applies to runtime application code, not schema migrations. Migrations operate on the schema and can use raw `op.execute()` / bulk update statements for data backfills. This is intentional and not a violation.

6. **No commented-out code in migrations.** If a migration is superseded, move it to `archive/` rather than commenting it out.

## Adding schema changes — step by step

1. **Update the SQLAlchemy model** in `src/giljo_mcp/models/`.
2. **Decide chain** using the routing decision tree above.
3. **Generate a revision** with `alembic revision -m "your_change_description"` (or hand-author if you know the pattern).
4. **Make the upgrade idempotent** (see hard rule 2).
5. **Implement the downgrade** — even if you think nobody will use it. Downgrade is the rollback path for failed installs.
6. **If it's a column on an existing baseline table**, also update the baseline (`baseline_v38_unified.py`) so fresh installs get the column directly without needing the incremental migration to also run. The incremental migration's idempotency guard will make it a no-op on fresh installs.
7. **Test locally:** `python startup.py --verbose` — confirms `alembic upgrade head` runs cleanly.
8. **Commit** the model change + migration file together in one commit.

## SaaS migrations

`saas_versions/` is loaded by `migrations/env.py` only when `GILJO_MODE=saas`. The Table Existence Rule (CLAUDE.md) forbids CE code from referencing SaaS-only tables — that's enforced at runtime by SQLAlchemy errors and at CI by the "SaaS table references in CE" check.

If you find yourself needing a column on a CE model that ONLY makes sense in SaaS, that's a sign the column is in the wrong place — either move the model into `saas/models/` or rethink the design.

## When in doubt

Cite the project ID in your commit message and ask the orchestrator. Migration mistakes are expensive to roll back from a running install — the cost of a 5-minute clarification beats the cost of an emergency hotfix.
