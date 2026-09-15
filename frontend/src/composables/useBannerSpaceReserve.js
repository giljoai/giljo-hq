import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const BANNER_ROW_PX = 42
const RESERVE_STORAGE_KEY = 'giljo_banner_reserved_rows'
const RESERVE_ROW_CAP = 3
const SETTLE_TIMEOUT_MS = 4000

function readReserveRecord() {
  try {
    const rec = JSON.parse(localStorage.getItem(RESERVE_STORAGE_KEY) ?? 'null')
    const n = Number.isFinite(rec?.n) ? Math.min(Math.max(rec.n, 0), RESERVE_ROW_CAP) : 0
    return { owner: typeof rec?.u === 'string' ? rec.u : '', rows: n }
  } catch {
    return { owner: '', rows: 0 }
  }
}

export function useBannerSpaceReserve({ visibleBannerKeys, currentUserId }) {
  const reserveRecord = readReserveRecord()
  const reservedRows = ref(reserveRecord.rows)
  const settled = ref(false)

  watch(
    () => currentUserId.value,
    (id) => {
      if (id && reserveRecord.owner && String(id) !== reserveRecord.owner) {
        reservedRows.value = 0
      }
    },
    { immediate: true },
  )

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
