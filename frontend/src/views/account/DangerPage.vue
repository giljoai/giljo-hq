<template>
  <div class="danger-page" data-test="danger-page">
    <h2 class="text-title-large mb-1">Danger Zone</h2>
    <p class="text-body-medium mb-4 danger-subtitle">
      Account-level actions. These are permanent — proceed carefully.
    </p>

    <div class="danger-top">
      <div
        v-if="canExportData"
        class="danger-card danger-card--enabled smooth-border"
        data-test="download-my-data-section"
        :style="{ '--card-accent': 'var(--color-accent-primary)' }"
      >
        <div
          class="danger-card-icon"
          :style="{ background: 'rgba(255,195,0,0.12)', color: 'var(--color-accent-primary)' }"
        >
          <v-icon size="20">mdi-download-outline</v-icon>
        </div>
        <div class="danger-card-body">
          <div class="danger-card-title">Download my data</div>
          <div class="danger-card-desc">
            Download all your data as a portable ZIP. Includes products, projects, vision documents,
            agents, memory, tasks, and configuration. Credentials are redacted.
          </div>

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

          <div v-if="exportResult" class="export-result" data-test="export-result">
            <a
              v-if="!exportLinkUsed"
              :href="exportResult.download_url"
              class="export-download-link"
              data-test="export-download-link"
              download
              @click="exportLinkUsed = true"
            >
              <v-icon size="16" class="mr-1">mdi-download</v-icon>
              Download tenant_export.zip
            </a>
            <v-btn
              v-else
              variant="text"
              size="small"
              color="warning"
              prepend-icon="mdi-refresh"
              data-test="export-generate-new-link-btn"
              @click="onGenerateExport"
            >
              Generate a new link
            </v-btn>
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

    <component :is="DangerZoneRestore" v-if="isSaas && DangerZoneRestore" />

    <div
      v-if="canEditPrompt"
      class="prompt-section danger-card danger-card--enabled smooth-border"
      data-test="orchestrator-prompt-section"
      :style="{ '--card-accent': 'var(--color-accent-primary)' }"
    >
      <div
        class="danger-card-icon"
        :style="{ background: 'rgba(255,195,0,0.12)', color: 'var(--color-accent-primary)' }"
      >
        <v-icon size="20">mdi-file-document-edit-outline</v-icon>
      </div>
      <div class="danger-card-body">
        <div class="danger-card-title">Orchestrator prompt</div>
        <div class="danger-card-desc">
          The orchestrator-prompt editor moved to Tools &gt; Agents, beside the other
          account-wide agent settings.
        </div>
      </div>
      <div class="danger-card-action">
        <v-btn
          color="warning"
          variant="flat"
          data-test="orchestrator-prompt-link"
          @click="goToOrchestratorPrompt"
        >
          Open in Tools &gt; Agents
          <v-icon end>mdi-arrow-right</v-icon>
        </v-btn>
      </div>
    </div>

    <component
      :is="DeleteAccountDialog"
      v-if="isSaas && DeleteAccountDialog"
      v-model="showDeleteDialog"
      :has-active-subscription="hasActiveSubscription"
    />
  </div>
</template>

<script setup>
import { ref, shallowRef, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import configService from '@/services/configService'
import { useToast } from '@/composables/useToast'
import api from '@/services/api'
import { parseErrorResponse } from '@/utils/errorMessages'
import { useWebSocketStore } from '@/stores/websocket'
import { useUserStore } from '@/stores/user'

const router = useRouter()

function goToOrchestratorPrompt() {
  router.push({ path: '/tools', query: { tab: 'agents', view: 'prompt' } })
}

const showDeleteDialog = ref(false)
const DeleteAccountDialog = shallowRef(null)
const DangerZoneRestore = shallowRef(null)
const { showToast } = useToast()

const isCe = computed(() => configService.getEdition() === 'community')
const isSaas = computed(() => configService.getEdition() !== 'community')

const userStore = useUserStore()
const canExportData = computed(() => {
  if (isCe.value) return true
  return isSaas.value && userStore.isAdmin
})

const canEditPrompt = computed(() => userStore.isAdmin)

const exporting = ref(false)
const exportError = ref('')
const exportProgress = ref(null)
const exportResult = ref(null)
const exportLinkUsed = ref(false)

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

const ws = useWebSocketStore()
let unsubscribeExportProgress = null

function handleExportProgress(payload) {
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
  exportLinkUsed.value = false

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
    const message = parseErrorResponse(err).message || 'Could not generate export. Please try again.'
    exportError.value = message
    showToast({ message, type: 'error' })
  } finally {
    exporting.value = false
  }
}

const accountStateStoreRef = shallowRef(null)
const hasPendingDeletion = computed(
  () => accountStateStoreRef.value?.isAccountScheduledForDeletion ?? false,
)
const cardAccent = computed(() =>
  hasPendingDeletion.value ? 'var(--color-accent-primary)' : 'rgb(var(--v-theme-error))',
)
const cancellingDeletion = ref(false)
const checkingDeleteEligibility = ref(false)

const hasActiveSubscription = computed(
  () => accountStateStoreRef.value?.hasCurrentPaidSubscription ?? false,
)

async function onOpenDeleteAccount() {
  const store = accountStateStoreRef.value
  checkingDeleteEligibility.value = true
  try {
    if (store?.fetchStatus) {
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
    showToast({
      message: parseErrorResponse(err).message || 'Could not cancel deletion. Please try again.',
      type: 'error',
    })
  } finally {
    cancellingDeletion.value = false
  }
}

const dlgLoaders = import.meta.glob('@/saas/components/DeleteAccountDialog.vue')

const acctStoreLoaders = import.meta.glob('@/saas/stores/useAccountStateStore.js')

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
      store.fetchStatus()
    } catch (e) {
      console.warn('[DangerPage] account-state store unavailable:', e?.message)
    }
  }

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
  color: var(--color-accent-primary);
}

.danger-card-title--warning {
  color: var(--color-accent-primary);
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
  color: var(--color-accent-primary);
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
