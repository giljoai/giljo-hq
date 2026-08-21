# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Agent Message Hub (BBS) models — BE-6054a (Data Foundation).

A persistent, tenant-isolated message board that unifies project-anchored
agent chatter with standalone (project-less) chat threads. The unit is the
**thread**, not the project — a thread has no jobs / agents / closeout-to-memory
machinery, so it never pollutes the project entity or fires closeout on a
perpetual chat.

Two tables:

- ``comm_threads`` — the thread entity. Carries a ``CHT-####`` serial (minted
  via the existing taxonomy seam, soft-delete-aware counter), a loose status
  lifecycle, the ``next_action_owner`` baton (the keystone: *which threads await
  me?*), an optional ``product_id`` filter dim, and an optional ``project_id``
  (NULL = standalone, non-null = project-anchored). ``resolution`` is a
  validated JSONB blob.
- ``comm_participants`` — the directory of standalone participants **and the
  user**. Project-anchored threads draw their agent roster from the existing
  ``AgentExecution`` / ``CH_TEAM`` machinery (no duplication — see BE-6008's
  staged messageable-identity precedent); this table covers only what that
  misses.

Edition Scope: CE. These are CE (tenant_key) tables in ``migrations/versions/``;
no ``saas/`` import, no SaaS-only table reference.
"""

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func, text

from giljo_mcp.utils.taxonomy_alias import format_taxonomy_alias

from .base import Base, generate_uuid


# Loose status lifecycle. NOT a DB enum — the column accepts these plus a
# freeform label so the board can carry vendor-specific states without a
# migration. ``resolved`` / ``closed`` are the terminal states that the
# loop/sleep coordination (BE-6054c) treats as "stop looping".
VALID_THREAD_STATUSES = ("open", "active", "resolved", "closed")
TERMINAL_THREAD_STATUSES = ("resolved", "closed")

# The serial prefix minted for every thread (CHT-0001 ...). Mirrors the reserved
# task tag (TSK) concept: a runtime-only taxonomy type, never project-selectable.
CHT_TAXONOMY_ABBR = "CHT"

# BE-6054c: messages.message_type marker for a user-armed loop/sleep directive.
# A free-string value (no migration); an addressed agent with such a message on a
# NON-terminal thread gets the "loop until resolved/closed" directive composed
# into its mission. The loop terminates when the thread reaches a terminal status.
LOOP_DIRECTIVE_MESSAGE_TYPE = "loop_directive"

# Participant directory types.
VALID_PARTICIPANT_TYPES = ("agent", "user")

# BE-9475: what a participant may declare about ITSELF via post_to_thread(my_status=...).
#
# LOCKED to the dot vocabulary the operator already knows — frontend/src/utils/
# statusConfig.js maps exactly these six, and the Jobs board renders them with the same
# colours. A seventh value would reach getStatusColor with no entry and render #666666
# "Unknown", which is a worse answer than the NULL it replaced. So this is a closed set,
# not a starting set: adding to it means adding a colour, and that is a design decision
# about the whole dashboard rather than about this table.
#
# Deliberately NARROWER than agent_executions.status, which also carries closed / silent /
# decommissioned / awaiting_user / staged. Those are lifecycle facts the PLATFORM
# establishes about an agent it is running; an agent may not award them to itself.
VALID_SELF_REPORTED_STATUSES = ("working", "waiting", "blocked", "idle", "sleeping", "complete")

# BE-9012d (D8/D9): the subject stamped on a project-bound thread that the system
# auto-creates when a project has no bound thread yet. The shared resolver
# (CommThreadService.resolve_or_create_bound_thread), the ce_0072 fold migration,
# and the D1(a) 360-pane all agree on "THE project's bound thread" via one
# precedence: exactly-one -> that thread (any subject); none -> create with THIS
# marker; several -> the marker-subject one if present, else the oldest. The marker
# is only how a *system-created* bound thread is recognised — resolution never keys
# on it alone (an organic chain hub is reused, not duplicated).
BOUND_THREAD_MARKER_SUBJECT = "(project comms)"


class CommThread(Base):
    """A message-board thread (standalone or project-anchored).

    The serial integer is minted per-tenant (max+1) at create time; the
    human-facing handle is ``CHT-{serial:04d}`` via ``taxonomy_alias``.
    """

    __tablename__ = "comm_threads"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_key = Column(String(36), nullable=False)
    # CHT serial integer (per-tenant max+1). The CHT-#### alias is derived.
    serial = Column(Integer, nullable=False)
    subject = Column(String(255), nullable=True)
    # Loose enum (open|active|resolved|closed) + freeform label tolerated.
    status = Column(String(50), nullable=False, server_default="open")
    # The baton: agent_id | user_id | 'all' | 'none' (NULL = unset).
    next_action_owner = Column(String(255), nullable=True)
    severity = Column(String(20), nullable=True)
    # Optional filter dim — standalone threads may have no product.
    product_id = Column(String(36), ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    # NULL = standalone thread; non-null = project-anchored. BE-9012d (D10): the
    # binding is lifecycle-shared — ``ondelete=CASCADE`` (was SET NULL) so a genuine
    # project purge (nuclear_delete / the 10-day auto-purge) takes the project's
    # bound thread with it instead of orphaning it into the town square. Soft-delete
    # never fires the FK, so a recoverable project keeps its thread for restore. The
    # rest of the chain (messages.thread_id, the message junctions, comm_participants)
    # is already CASCADE, so this completes it. Applied to existing DBs by ce_0072.
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    # Validated structured resolution blob (see jsonb_validators.CommThreadResolution).
    resolution = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    # Soft delete (ce_0057): NULL = live thread, non-NULL = deleted. The CHT serial
    # counter (mint_serial) deliberately keeps counting deleted rows so a freed
    # serial is never reused. All reads filter deleted_at IS NULL.
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    # BE-9291: THE chain run this thread is the coordination hub for. NULL on every
    # thread that is not a chain hub, which is nearly all of them — hence nullable.
    #
    # This replaces a free-text convention with a structural link. The run_id used to
    # be substring-searched out of ``subject`` (the conductor's seed instruction put it
    # there and told sub-orchestrators to find their hub with search_threads(run_id)),
    # which made a display field load-bearing lookup machinery whose failure mode was
    # SILENT: nothing raised, the sub-orchestrator just never found its hub.
    #
    # ``ondelete=SET NULL`` is load-bearing, not a default. A finished run is PURGED
    # (SequenceRunService.purge_run, BE-6189) — the chain grouping is ephemeral while
    # the conversation is durable, so the hub must OUTLIVE its run. CASCADE would
    # delete the thread and its whole message history when the chain completed
    # normally, and RESTRICT would make purge_run raise. Discovery tolerates the
    # resulting NULL: post-purge there is no run left to discover a hub for.
    sequence_run_id = Column(String(36), ForeignKey("sequence_runs.id", ondelete="SET NULL"), nullable=True)

    participants = relationship("CommParticipant", back_populates="thread", cascade="all, delete-orphan")

    __table_args__ = (
        # One CHT serial per tenant — prevents a duplicate CHT-#### handle.
        # BE-8000c: idx_comm_thread_tenant dropped — leftmost-covered by the
        # tenant-leading composites (owner / status) and uq_comm_thread_serial.
        UniqueConstraint("tenant_key", "serial", name="uq_comm_thread_serial"),
        # The baton query (get_my_turn): threads where next_action_owner == me.
        Index("idx_comm_thread_owner", "tenant_key", "next_action_owner"),
        Index("idx_comm_thread_status", "tenant_key", "status"),
        # TSK-9076: backup watermark sweep — MAX(updated_at) per tenant.
        Index("idx_comm_threads_tenant_updated", "tenant_key", "updated_at"),
        Index("idx_comm_thread_product", "product_id"),
        Index("idx_comm_thread_project", "project_id"),
        # BE-9291: the chain-hub discovery lookup. PARTIAL — hub threads are a tiny
        # minority, so indexing only the non-NULL rows keeps this a few pages instead
        # of one entry per thread on the board.
        Index(
            "idx_comm_thread_sequence_run",
            "tenant_key",
            "sequence_run_id",
            postgresql_where=text("sequence_run_id IS NOT NULL"),
        ),
    )

    @property
    def taxonomy_alias(self) -> str:
        """Human-facing handle, e.g. ``CHT-0042`` (never truncated)."""
        return format_taxonomy_alias(CHT_TAXONOMY_ABBR, self.serial)

    def __repr__(self) -> str:
        return f"<CommThread(id={self.id}, alias='{self.taxonomy_alias}', status='{self.status}')>"


class CommParticipant(Base):
    """A directory entry: a standalone agent participant OR the user.

    Project-anchored threads reuse the existing agent roster; this table covers
    standalone participants + the user only (no duplication of the live roster).
    """

    __tablename__ = "comm_participants"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_key = Column(String(36), nullable=False)
    thread_id = Column(String(36), ForeignKey("comm_threads.id", ondelete="CASCADE"), nullable=False)
    # agent_id or user_id (string identity, BE-6008 staged-identity compatible).
    participant_id = Column(String(255), nullable=False)
    participant_type = Column(String(20), nullable=False)  # 'agent' | 'user'
    display_name = Column(String(255), nullable=True)
    role = Column(String(50), nullable=True)
    # BE-9289a: the harness driving this participant's session (claude-code / codex /
    # gemini / antigravity / opencode / generic). Stamped SERVER-SIDE from the MCP
    # ``initialize`` handshake via harness_resolver.harness_from_client_info — NEVER
    # self-declared, so no local instruction file can change what the Hub renders.
    # ``generic`` is the fail-safe floor (REST posts, in-memory transport, unknown
    # clientInfo). Deliberately NOT accompanied by a host/machine-name column: the
    # server cannot know a client's hostname, so it would have to be volunteered by
    # the agent — the exact self-declaration this step removes.
    harness = Column(String(32), nullable=True)
    joined_at = Column(DateTime(timezone=True), server_default=func.now())
    # BE-9289a: last activity of ANY kind on this thread (post, read, or baton poll),
    # so a live/idle dot is derivable without a second presence mechanism. NULL = the
    # participant was enrolled but has never acted.
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    # BE-9012a (D6): server-persistent per-(thread, participant) read cursor.
    # ``last_read_at`` is the load-bearing filter — the unread read keys on
    # ``Message.created_at > last_read_at``, which is reaper-safe (a reaped message
    # id can never strand the cursor). ``last_read_message_id`` records the exact
    # boundary post for reference/UI. Both NULL = nothing read yet on this thread
    # (unread = the whole timeline — honest "never read" semantics, no FK so a
    # deleted message leaves a harmless stale id, never a broken constraint).
    last_read_message_id = Column(String(36), nullable=True)
    last_read_at = Column(DateTime(timezone=True), nullable=True)
    # BE-9475: what this participant says it is DOING, self-declared on post_to_thread.
    #
    # Exists for one reason: a headless agent has no agent_executions row, so the Hub's
    # execution-status subquery serves it NULL forever and the client renders that as
    # idle / "Monitoring" — a lane looks like it is watching a screen the whole time it
    # is saturating a core, and nothing it can do changes that. This column is the only
    # channel such a participant has.
    #
    # STRICTLY A FALLBACK. agent_executions wins whenever a row exists (see
    # participant_display_status). A self-declaration must never be able to contradict
    # the Jobs board about an agent the platform is actually running.
    #
    # Constrained by VALID_SELF_REPORTED_STATUSES at the write boundary rather than by a
    # DB CHECK: a constraint violation surfaces as a 500, and this value arrives from an
    # AI agent, which is exactly the input class that must get a 422-shaped refusal
    # naming the valid set so it can self-correct.
    self_reported_status = Column(String(20), nullable=True)
    # When that declaration was made. Recorded, not read by the dot — a status with no
    # age cannot later be aged out, and reintroducing a time window here would resurrect
    # the isAgentLive liveness green FE-9365c deliberately removed. Kept for operator
    # forensics ("it said working, but when?"), which is why it is stamped and not read.
    self_reported_status_at = Column(DateTime(timezone=True), nullable=True)

    thread = relationship("CommThread", back_populates="participants")

    __table_args__ = (
        # A participant joins a thread at most once (collision-safe re-join).
        # BE-8000c: idx_comm_participant_tenant dropped (leftmost-covered by
        # idx_comm_participant_lookup); idx_comm_participant_thread dropped
        # (leftmost-covered by uq_comm_participant on thread_id).
        UniqueConstraint("thread_id", "participant_id", name="uq_comm_participant"),
        Index("idx_comm_participant_lookup", "tenant_key", "participant_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<CommParticipant(thread_id={self.thread_id}, "
            f"participant_id={self.participant_id}, type={self.participant_type})>"
        )
