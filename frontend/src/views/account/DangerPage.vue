<template>
  <div class="danger-page" data-test="danger-page">
    <h2 class="text-title-large mb-1">Danger Zone</h2>
    <p class="text-body-medium mb-4 danger-subtitle">
      Account-level actions. These are permanent — proceed carefully.
    </p>

    <!-- IMP-5042 layout: Export + Account-deletion as a 2-up row; the
         orchestrator-prompt editor sits full-width beneath. -->
    <div class="danger-top">
      <!--
      Download My Data (BE-5062 — GDPR data portability).
      Visible in CE (single-user, no role gate) and in SaaS for org admins.
      Server gates the endpoint itself; this v-if is UX hygiene.
    -->
      <div
        v-if="canExportData"
        class="danger-card danger-card--enabled smooth-border"
        data-test="download-my-data-section"
        :style="{ '--card-accent': 'var(--brand-yellow)' }"
      >
        <div
          class="danger-card-icon"
          :style="{ background: 'rgba(255,195,0,0.12)', color: 'var(--brand-yellow)' }"
        >
          <v-icon size="20">mdi-download-outline</v-icon>
        </div>
        <div class="danger-card-body">
          <div class="danger-card-title">Download my data</div>
          <div class="danger-card-desc">
            Download all your data as a portable ZIP. Includes products, projects, vision documents,
            agents, memory, tasks, and configuration. Credentials are redacted.
          </div>

          <!-- Progress feed (driven by WebSocket tenant:export_progress events). -->
          <div
            v-if="exporting || exportProgress"
            class="export-progress"
            data-test="export-progress"
          >
            <v-progress-linear
              :model-value="exportPercent"
              :indeterminate="exporting && !exportProgress"
              color="warning"
              height="4"
              class="mb-2"
            />
            <div class="export-progress-status" data-test="export-progress-status">
              {{ exportStatusText }}
            </div>
          </div>

          <!-- Completed: download link + expiry + model counts. -->
          <div v-if="exportResult" class="export-result" data-test="export-result">
            <a
              :href="exportResult.download_url"
              class="export-download-link"
              data-test="export-download-link"
              download
            >
              <v-icon size="16" class="mr-1">mdi-download</v-icon>
              Download tenant_export.zip
            </a>
            <div class="export-expiry" data-test="export-expiry">
              Link expires {{ expiresAtFormatted }}
            </div>
            <ul
              v-if="modelCountEntries.length"
              class="export-model-counts"
              data-test="export-model-counts"
            >
              <li v-for="[model, count] in modelCountEntries" :key="model">
                <span class="model-name">{{ model }}</span>
                <span class="model-count">{{ count }}</span>
              </li>
            </ul>
          </div>

          <!-- Error surface. -->
          <div v-if="exportError" class="export-error" data-test="export-error">
            {{ exportError }}
          </div>
        </div>
        <div class="danger-card-action">
          <v-btn
            color="warning"
            variant="flat"
            :loading="exporting"
            :disabled="exporting"
            data-test="generate-export-btn"
            @click="onGenerateExport"
          >
            {{ exportResult ? 'Generate again' : 'Generate export' }}
            <v-icon end>mdi-arrow-right</v-icon>
          </v-btn>
        </div>
      </div>

      <!-- Delete card (SaaS-only) -->
      <div
        v-if="isSaas"
        class="danger-card danger-card--enabled smooth-border"
        data-test="delete-account-card"
        :style="{ '--card-accent': cardAccent }"
      >
        <div
          class="danger-card-icon"
          :class="{
            'danger-card-icon--danger': !hasPendingDeletion,
            'danger-card-icon--warning': hasPendingDeletion,
          }"
        >
          <v-icon size="20">{{
            hasPendingDeletion ? 'mdi-clock-alert-outline' : 'mdi-trash-can-outline'
          }}</v-icon>
        </div>
        <div class="danger-card-body">
          <div
            class="danger-card-title"
            :class="{
              'danger-card-title--danger': !hasPendingDeletion,
              'danger-card-title--warning': hasPendingDeletion,
            }"
          >
            {{ hasPendingDeletion ? 'Pending account deletion' : 'Delete my account' }}
          </div>
          <div class="danger-card-desc">
            <template v-if="hasPendingDeletion">
              Your account is scheduled for permanent deletion on
              <strong>{{ accountStateStoreRef?.purgeAfterFormatted }}</strong
              >. You can still cancel and restore full access.
            </template>
            <template v-else>
              Permanently remove your account and tenant data. We'll email you a confirmation link
              with a 24-hour window before anything is changed.
            </template>
          </div>
        </div>
        <div class="danger-card-action">
          <!-- when a deletion is pending or confirmed, the SAFE
             primary action is "Cancel pending deletion" (warning, not red). -->
          <v-btn
            v-if="hasPendingDeletion"
            color="warning"
            variant="flat"
            :loading="cancellingDeletion"
            data-test="cancel-pending-deletion-btn"
            @click="onCancelPendingDeletion"
          >
            Cancel pending deletion
            <v-icon end>mdi-arrow-right</v-icon>
          </v-btn>
          <v-btn
            v-else
            color="error"
            variant="flat"
            :loading="checkingDeleteEligibility"
            data-test="open-delete-account-dialog"
            @click="onOpenDeleteAccount"
          >
            Delete account
            <v-icon end>mdi-arrow-right</v-icon>
          </v-btn>
        </div>
      </div>
    </div>

    <!--
      FE-6130h: Backup & restore self-service (SaaS-only). Extracted into its own
      saas/ component to keep DangerPage under the 800-line file-size limit and
      to keep the /api/saas/account/* path strings + request-restore dialog out of
      the CE bundle. Lazy-glob loaded (CE export strips saas/ → glob empties → the
      component stays null and never renders), gated SaaS-only.
    -->
    <component :is="DangerZoneRestore" v-if="isSaas && DangerZoneRestore" />

    <!--
      Orchestrator prompt (IMP-5042). Tenant-scoped power-user setting relocated
      here from the admin panel: editing it can break orchestrator coordination,
      so it belongs in the Danger Zone. Rendered full-width beneath the 2-up row
      so the editor has room. Admin-only — the /orchestrator-prompt endpoints are
      require_admin, so a non-admin member never sees or reaches it.
    -->
    <div v-if="canEditPrompt" class="prompt-section" data-test="orchestrator-prompt-section">
      <SystemPromptTab />
    </div>

    <!-- Lazy-load the SaaS-only dialog so the import never appears in CE bundles.
         BE-9040d: the old "cancel your subscription first in Billing" dead-end dialog
         is removed — deletion now auto-cancels the subscription. The dialog shows a
         pro-rata-forfeit notice when the account has an active subscription. -->
    <component
      :is="DeleteAccountDialog"
      v-if="isSaas && DeleteAccountDialog"
      v-model="showDeleteDialog"
      :has-active-subscription="hasActiveSubscription"
    />
  </div>
</template>

<script setup>
/**
 * Account "Danger Zone" sub-tab.
 *
 * Two stacked accent-bordered cards (Export, Delete) using the same
 * smooth-border + accent-stripe pattern as WelcomeView quick-launch cards.
 *
 * Edition gating:
 * - Export card is edition-neutral (still a stub for both editions).
 * - Delete card and its dialog are SaaS-only — gated via configService and
 *   the dialog is dynamically imported from saas/, so neither the import
 *   nor the deletion path strings end up in the CE bundle.
 */
import { ref, shallowRef, computed, onMounted, onBeforeUnmount } from 'vue'
import configService from '@/services/configService'
import { useToast } from '@/composables/useToast'
import api from '@/services/api'
import { useWebSocketStore } from '@/stores/websocket'
import { useUserStore } from '@/stores/user'
import SystemPromptTab from '@/components/settings/tabs/SystemPromptTab.vue'

const showDeleteDialog = ref(false)
const DeleteAccountDialog = shallowRef(null)
// FE-6130h: SaaS-only backup & restore controls, extracted to its own saas/
// component and lazy-glob loaded so it never enters the CE bundle.
const DangerZoneRestore = shallowRef(null)
const { showToast } = useToast()

// Edition flags. `getEdition()` returns 'community' for GILJO_MODE=ce, 'saas'
// for saas. We use this for visibility of CE-only / SaaS-only affordances on
// this page (matches the existing pattern for the SaaS-only delete card).
// configService is the mode source of truth for components rendered well after
// initial navigation (ADR-002 § "Rule 1").
const isCe = computed(() => configService.getEdition() === 'community')
const isSaas = computed(() => configService.getEdition() !== 'community')

// BE-5062: Download My Data is available in CE (single-user, no role gate)
// and in SaaS for org admins. Tenant isolation is enforced server-side regardless.
const userStore = useUserStore()
const canExportData = computed(() => {
  if (isCe.value) return true
  return isSaas.value && userStore.isAdmin
})

// IMP-5042: the orchestrator-prompt editor is admin-only (its endpoints are
// require_admin). In CE and SaaS Solo the single user is the admin, so they see
// it; a future Team non-admin member does not.
const canEditPrompt = computed(() => userStore.isAdmin)

// ---------------------------------------------------------------------------
// BE-5062 — Download My Data
// ---------------------------------------------------------------------------
const exporting = ref(false)
const exportError = ref('')
// Latest WebSocket progress frame: { model, current, total, phase }.
const exportProgress = ref(null)
// Final result from POST /api/v1/account/export:
//   { download_url, expires_at, model_counts }
const exportResult = ref(null)

const exportPercent = computed(() => {
  const p = exportProgress.value
  if (!p) return 0
  if (p.phase === 'complete') return 100
  if (!p.total || p.total <= 0) return 0
  return Math.min(100, Math.round((p.current / p.total) * 100))
})

const exportStatusText = computed(() => {
  const p = exportProgress.value
  if (!p) return 'Preparing export…'
  if (p.phase === 'complete') {
    return p.records != null ? `Export complete — ${p.records} records.` : 'Export complete.'
  }
  // "exporting" phase — model + counts.
  const model = p.model || '…'
  return `Exporting ${model} (${p.current} / ${p.total})…`
})

const expiresAtFormatted = computed(() => {
  const iso = exportResult.value?.expires_at
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
})

const modelCountEntries = computed(() => {
  const counts = exportResult.value?.model_counts
  if (!counts || typeof counts !== 'object') return []
  return Object.entries(counts).sort(([a], [b]) => a.localeCompare(b))
})

// Subscribe to tenant:export_progress on the shared WebSocket connection.
// ws.on(...) returns an unsubscribe function — we capture it so the handler
// doesn't leak past this component's lifetime.
const ws = useWebSocketStore()
let unsubscribeExportProgress = null

function handleExportProgress(payload) {
  // Payload is normalized to the flat data shape by the WS store; the data
  // field may be nested or flat depending on transport. Read defensively.
  const data = payload?.data && typeof payload.data === 'object' ? payload.data : payload
  if (!data) return
  exportProgress.value = {
    model: data.model ?? '',
    current: Number(data.current ?? 0),
    total: Number(data.total ?? 0),
    records: data.records != null ? Number(data.records) : null,
    phase: data.phase ?? 'exporting',
  }
}

async function onGenerateExport() {
  if (exporting.value) return
  exporting.value = true
  exportError.value = ''
  exportProgress.value = null
  exportResult.value = null

  // Subscribe lazily on first click so we don't pay handler cost for users
  // who never trigger an export.
  if (!unsubscribeExportProgress) {
    unsubscribeExportProgress = ws.on('tenant:export_progress', handleExportProgress)
  }

  try {
    const response = await api.account.exportMyData()
    const body = response?.data ?? response
    exportResult.value = {
      download_url: body?.download_url ?? '',
      expires_at: body?.expires_at ?? '',
      model_counts: body?.model_counts ?? {},
    }
    if (!exportResult.value.download_url) {
      throw new Error('Backend did not return a download URL.')
    }
  } catch (err) {
    // Backend exception handlers can return either { detail } (FastAPI default)
    // or { error_code, message, timestamp } (wrapped). Surface either, plus
    // the 403 "Data export is not available in this edition." case.
    const data = err?.response?.data
    const message =
      data?.detail ||
      data?.message ||
      err?.message ||
      'Could not generate export. Please try again.'
    exportError.value = message
    showToast({ message, type: 'error' })
  } finally {
    exporting.value = false
  }
}

// lazy account-state store handle (CE-export safe).
const accountStateStoreRef = shallowRef(null)
const hasPendingDeletion = computed(
  () => accountStateStoreRef.value?.isAccountScheduledForDeletion ?? false,
)
const cardAccent = computed(() =>
  hasPendingDeletion.value ? 'var(--brand-yellow)' : 'rgb(var(--v-theme-error))',
)
const cancellingDeletion = ref(false)
const checkingDeleteEligibility = ref(false)

// BE-9040d: an active paid subscription no longer BLOCKS deletion — it is
// auto-cancelled as part of the delete flow. We still read the flag so the
// confirmation dialog can show the pro-rata-forfeit notice (access ends now,
// no further charges, remaining paid days forfeited, no refund).
const hasActiveSubscription = computed(
  () => accountStateStoreRef.value?.hasCurrentPaidSubscription ?? false,
)

async function onOpenDeleteAccount() {
  const store = accountStateStoreRef.value
  checkingDeleteEligibility.value = true
  try {
    if (store?.fetchStatus) {
      // Refresh subscription state so the dialog's forfeit notice reflects the
      // live plan — bypass the short-TTL dedupe cache (FE-6059).
      await store.fetchStatus({ force: true })
    }
    showDeleteDialog.value = true
  } finally {
    checkingDeleteEligibility.value = false
  }
}

async function onCancelPendingDeletion() {
  const store = accountStateStoreRef.value
  if (!store || cancellingDeletion.value) return
  cancellingDeletion.value = true
  try {
    await store.cancelDeletion()
    showToast({ message: 'Account deletion cancelled.', type: 'success' })
  } catch (err) {
    const detail = err?.response?.data?.detail
    showToast({
      message: detail || 'Could not cancel deletion. Please try again.',
      type: 'error',
    })
  } finally {
    cancellingDeletion.value = false
  }
}

// CE-export safety: use Vite's static glob discovery so the import string
// is *not* statically bound to a path that may have been stripped from the
// CE tree. In CE builds saas/ is removed before `vite build` runs, the glob
// resolves to an empty map, and DeleteAccountDialog stays null (and the
// gating v-if above keeps the card off the page anyway). Same pattern as
// main.js uses to load saas/routes/index.js.
const dlgLoaders = import.meta.glob('@/saas/components/DeleteAccountDialog.vue')

// also lazy-load the account-state store so the Cancel-pending
// affordance can read deletion status. CE export drops both globs.
const acctStoreLoaders = import.meta.glob('@/saas/stores/useAccountStateStore.js')

// FE-6130h: lazy-load the SaaS-only backup & restore controls component.
// Same static-glob pattern — CE export strips saas/ so the glob resolves to an
// empty map in CE builds and the component stays null (never rendered).
const restoreSectionLoaders = import.meta.glob('@/saas/components/account/DangerZoneRestore.vue')

onBeforeUnmount(() => {
  if (unsubscribeExportProgress) {
    try {
      unsubscribeExportProgress()
    } catch {
      /* already removed */
    }
    unsubscribeExportProgress = null
  }
})

onMounted(async () => {
  if (!isSaas.value) return
  const [loader] = Object.values(dlgLoaders)
  if (loader) {
    try {
      const mod = await loader()
      DeleteAccountDialog.value = mod.default
    } catch (e) {
      console.warn('[DangerPage] DeleteAccountDialog unavailable:', e?.message)
    }
  }
  const [storeLoader] = Object.values(acctStoreLoaders)
  if (storeLoader) {
    try {
      const mod = await storeLoader()
      const store = mod.useAccountStateStore()
      accountStateStoreRef.value = store
      // Refresh on mount in case the user landed here directly.
      store.fetchStatus()
    } catch (e) {
      console.warn('[DangerPage] account-state store unavailable:', e?.message)
    }
  }

  // FE-6130h: load the SaaS-only backup & restore controls component. It owns
  // its own state/API calls (statically imported from saas/), so DangerPage just
  // mounts it once resolved.
  const [restoreSectionLoader] = Object.values(restoreSectionLoaders)
  if (restoreSectionLoader) {
    try {
      const mod = await restoreSectionLoader()
      DangerZoneRestore.value = mod.default
    } catch (e) {
      console.warn('[DangerPage] DangerZoneRestore unavailable:', e?.message)
    }
  }
})
</script>

<style lang="scss" scoped>
.danger-page {
  /* IMP-5042: widened from 720 to fit the 2-up Export/Delete row plus a
     full-width orchestrator-prompt editor beneath. Capped by the parent v-container. */
  max-width: 1040px;
  margin: 0 auto;
}

/* IMP-5042 layout: Export + Account-deletion as a 2-up row that collapses to a
   single column on narrow screens; the prompt editor renders full-width below. */
.danger-top {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
  gap: 14px;
  /* IMP-5042: stretch so both cards in the 2-up row share the tallest height;
     the per-card grid pins each button to the bottom so the row stays balanced. */
  align-items: stretch;
  margin-bottom: 14px;
}

.danger-top > .danger-card {
  /* grid gap handles row spacing; drop the stacked-card bottom margin */
  margin-bottom: 0;
}

.danger-subtitle {
  color: var(--text-secondary);
}

/* IMP-5042: spacing for the relocated orchestrator-prompt editor so it sits in
   the same vertical rhythm as the danger cards. */
.prompt-section {
  margin-bottom: 14px;
}

.danger-card {
  /* IMP-5042: grid so the action button drops to its own row beneath the
     text (full card width) instead of squeezing the title/description at
     half width. Row 1 (icon + body) takes 1fr and the action row sits at
     auto height, so with the stretch alignment above the button pins to the
     bottom edge and both cards line up. */
  display: grid;
  grid-template-columns: 40px 1fr;
  grid-template-rows: 1fr auto;
  grid-template-areas:
    'icon body'
    '.    action';
  column-gap: 16px;
  row-gap: 14px;
  /* Top-align icon + body so they don't drift to vertical center when the
     row grows to match the taller card. */
  align-items: start;
  padding: 18px 20px;
  background: rgb(var(--v-theme-surface));
  border-radius: 12px;
  position: relative;
  overflow: hidden;
  margin-bottom: 14px;
  transition:
    transform 200ms ease,
    box-shadow 200ms ease;
}

/* Left-edge accent stripe via CSS var (matches WelcomeView pattern). */
.danger-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  bottom: 0;
  width: 3px;
  background: var(--card-accent, transparent);
  opacity: 0.85;
}

.danger-card--enabled:hover {
  transform: translateY(-2px);
  box-shadow:
    inset 0 0 0 1px var(--smooth-border-color, rgba(255, 255, 255, 0.1)),
    0 8px 18px -6px rgba(0, 0, 0, 0.3);
}

.danger-card-icon {
  grid-area: icon;
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: grid;
  place-items: center;
}

.danger-card-icon--danger {
  /* rgba() form gives ~12% tint of theme error without hardcoding hex. */
  background: rgba(var(--v-theme-error), 0.12);
  color: rgb(var(--v-theme-error));
}

.danger-card-body {
  grid-area: body;
  /* min-width:0 lets long words/URLs wrap instead of forcing the grid wider. */
  min-width: 0;
}

.danger-card-title {
  font-size: 0.95rem;
  font-weight: 600;
  margin-bottom: 3px;
}

.danger-card-title--danger {
  color: rgb(var(--v-theme-error));
}

/* SAFE-action variant — yellow accent for "Cancel pending deletion". */
.danger-card-icon--warning {
  background: rgba(255, 195, 0, 0.12);
  color: var(--brand-yellow);
}

.danger-card-title--warning {
  color: var(--brand-yellow);
}

.danger-card-desc {
  font-size: 0.8rem;
  color: var(--text-secondary);
  line-height: 1.45;
}

.danger-card-action {
  grid-area: action;
  /* Button keeps its natural width, left-aligned under the description. */
  justify-self: start;
}

/* BE-5062: Download My Data — progress, result, error blocks
   Render inline below the description so the card grows naturally. */
.export-progress,
.export-result,
.export-error {
  margin-top: 12px;
}

.export-progress-status {
  font-size: 0.8rem;
  color: var(--text-secondary);
  line-height: 1.45;
}

.export-download-link {
  display: inline-flex;
  align-items: center;
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--brand-yellow);
  text-decoration: none;
}

.export-download-link:hover {
  text-decoration: underline;
}

.export-expiry {
  font-size: 0.75rem;
  color: var(--text-secondary);
  margin-top: 2px;
}

.export-model-counts {
  list-style: none;
  padding: 0;
  margin: 8px 0 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 4px 12px;
}

.export-model-counts li {
  display: flex;
  justify-content: space-between;
  font-size: 0.78rem;
  color: var(--text-secondary);
}

.export-model-counts .model-count {
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}

.export-error {
  font-size: 0.8rem;
  color: rgb(var(--v-theme-error));
  line-height: 1.45;
}
</style>
