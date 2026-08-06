/**
 * BE-9256 layer 4 — UI floor for legacy titleless git_commits rows.
 *
 * Stored 360/closeout rows already contain git_commits entries with an EMPTY
 * `message` (legacy bare-SHA normalization, pre-validator). The backend now
 * rejects NEW titleless commits (validate_git_commits), but old rows stay as
 * they are — code tolerates the old shape rather than a destructive migration
 * (data-facing-convention DoD). Every render surface must show a useful
 * floor for such rows: the short SHA, never a blank string or a bare "-".
 *
 * Shared by DashboardView.vue, CloseoutModal.vue, ProjectReviewModal.vue, and
 * MemoryEntryRow.vue so the fallback rule lives in exactly one place.
 */

const SHORT_SHA_LENGTH = 8

/** Truncate a commit sha to its short form. Returns '' for a missing/non-string sha. */
export function shortSha(sha, length = SHORT_SHA_LENGTH) {
  if (!sha || typeof sha !== 'string') return ''
  return sha.slice(0, length)
}

/**
 * Resolve the display title for a git_commits row.
 * - message present (non-blank) -> the message, unchanged.
 * - message empty/missing -> the short sha (the UI floor).
 * - sha ALSO missing -> '' (today's placeholder behavior; never invent data).
 */
export function commitTitle(commit) {
  if (!commit || typeof commit !== 'object') return ''
  const message = typeof commit.message === 'string' ? commit.message.trim() : ''
  if (message) return message
  return shortSha(commit.sha)
}
