/**
 * useBannerSpaceReserve.js — FE-9377, extracted by FE-9586
 *
 * First-frame space reservation for the banner strip, so a due banner never
 * shifts the page after paint. Extracted VERBATIM out of SystemStatusBanner.vue
 * (to keep that file within the project's file-size budget) to make room for the thread-post banner
 * family; the mechanism, the constants and the storage key are unchanged, and
 * SystemStatusBanner.reserve.fe9377.spec.js is the proof of that — it drives the
 * mounted component and was not touched by the extraction.
 *
 * Every row arms asynchronously, so a due banner used to insert after the page
 * content painted and shift the whole page down. The cure has to be known
 * SYNCHRONOUSLY at first render, and the only sync source of truth is what this
 * browser rendered last time: the settled row count is persisted to localStorage
 * and the next load reserves that height from the first frame. Rows that arrive
 * fill the reserved space in place (pendingReserveRows shrinks as
 * renderedRowCount grows — total strip height stays constant).
 *
 * The settle timer only matters for a STALE reservation (a cached row that no
 * longer arms — e.g. dismissed elsewhere, notification resolved server-side):
 * the leftover skeleton collapses at SETTLE_TIMEOUT_MS. Deliberately generous
 * and deliberately NOT short-circuited by per-source "done" signals — settling
 * early right before a slow fetch lands would turn one shift into two.
 *
 * The record carries the OWNING user id: a shared browser with two accounts must
 * not inherit the other account's reserved strip. Identity is NOT knowable at
 * first frame (the session cookie is httpOnly and /auth/me is async), so the
 * reservation renders optimistically from the stored record and is DROPPED the
 * moment the resolved user id disagrees with the record's owner — it can never
 * survive into the other account's steady state, and writes always stamp the
 * current owner.
 *
 * Edition Scope: Both
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

/** Height of one banner row (9px padding ×2 + 24px content — all rows nowrap). */
const BANNER_ROW_PX = 42
const RESERVE_STORAGE_KEY = 'giljo_banner_reserved_rows'
/** Reservation cap: never hold more than 3 rows of blank space on spec. */
const RESERVE_ROW_CAP = 3
const SETTLE_TIMEOUT_MS = 4000

/** Reads the stored {u: ownerUserId, n: rowCount} record; malformed → nothing. */
function readReserveRecord() {
  try {
    const rec = JSON.parse(localStorage.getItem(RESERVE_STORAGE_KEY) ?? 'null')
    const n = Number.isFinite(rec?.n) ? Math.min(Math.max(rec.n, 0), RESERVE_ROW_CAP) : 0
    return { owner: typeof rec?.u === 'string' ? rec.u : '', rows: n }
  } catch {
    return { owner: '', rows: 0 }
  }
}

/**
 * @param {object} sources
 * @param {import('vue').ComputedRef<Array<string>>} sources.visibleBannerKeys - useBannerFold's painted-row keys
 * @param {import('vue').ComputedRef<string|undefined>} sources.currentUserId - the resolved session identity, or undefined until it lands
 */
export function useBannerSpaceReserve({ visibleBannerKeys, currentUserId }) {
  const reserveRecord = readReserveRecord()
  const reservedRows = ref(reserveRecord.rows)
  const settled = ref(false)

  // Drop an inherited reservation as soon as the session's real identity lands.
  watch(
    () => currentUserId.value,
    (id) => {
      if (id && reserveRecord.owner && String(id) !== reserveRecord.owner) {
        reservedRows.value = 0
      }
    },
    { immediate: true },
  )

  // FE-9552: rows PAINTED = the visible-key set (1 collapsed, N expanded).
  const renderedRowCount = computed(() => visibleBannerKeys.value.length)

  const pendingReserveRows = computed(() =>
    settled.value ? 0 : Math.max(0, reservedRows.value - renderedRowCount.value),
  )

  let settleTimer = null
  onMounted(() => {
    settleTimer = setTimeout(() => {
      settled.value = true
    }, SETTLE_TIMEOUT_MS)
  })
  onBeforeUnmount(() => clearTimeout(settleTimer))

  // After settle, mirror the rendered count so the NEXT load's first frame
  // reserves exactly what this steady state shows (dismissals shrink it, newly
  // armed rows grow it). Stamped with the owning user id; no write until the
  // session's identity is known.
  watch(
    [settled, renderedRowCount, () => currentUserId.value],
    ([isSettled, count, userId]) => {
      if (isSettled && userId) {
        localStorage.setItem(
          RESERVE_STORAGE_KEY,
          JSON.stringify({ u: String(userId), n: Math.min(count, RESERVE_ROW_CAP) }),
        )
      }
    },
  )

  return { BANNER_ROW_PX, renderedRowCount, pendingReserveRows }
}
