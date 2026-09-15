<template>
  <v-dialog
    :model-value="show"
    :fullscreen="isMobile"
    :max-width="isMobile ? undefined : '1000'"
    persistent
    role="dialog"
    aria-labelledby="review-modal-title"
    data-testid="review-modal"
    @keydown.esc="$emit('close')"
  >
    <v-card class="smooth-border">
      <div id="review-modal-title" class="dlg-header">
        <v-icon class="dlg-icon">mdi-eye</v-icon>
        <div class="d-flex flex-column flex-grow-1">
          <span class="dlg-title">Project Review:
            <v-chip
              v-if="projectData?.taxonomy_alias && projectData?.project_type"
              :color="projectData.project_type.color"
              size="x-small"
              variant="flat"
              class="ml-1 mr-1"
              :title="projectData.project_type.label"
            >{{ projectData.taxonomy_alias }}</v-chip>
            <span class="review-project-name">{{ projectData?.name }}</span>
            <v-chip
              v-if="projectData?.status"
              :color="statusColor"
              :style="statusTextStyle"
              variant="flat"
              size="x-small"
              class="ml-2"
            >
              {{ projectData.status }}
            </v-chip>
          </span>
          <span class="text-body-small text-muted-a11y">
            <v-tooltip location="bottom">
              <template #activator="{ props: tp }">
                <span
                  v-bind="tp"
                  class="review-project-id"
                  role="button"
                  tabindex="0"
                  @click="copyProjectId"
                  @keydown.enter="copyProjectId"
                >{{ projectId }}</span>
              </template>
              <span>{{ copied ? 'Copied!' : 'Click to copy project ID' }}</span>
            </v-tooltip>
          </span>
        </div>
        <v-btn icon variant="text" size="small" class="dlg-close" @click="$emit('close')">
          <v-icon icon="mdi-close" size="18" />
        </v-btn>
      </div>

      <v-divider />

      <v-card-text class="pa-4 dialog-body-scroll">
        <v-progress-linear v-if="loading" indeterminate color="primary" />
        <v-alert v-if="error" type="error" variant="tonal" density="compact" class="mb-4">{{ error }}</v-alert>

        <template v-if="projectData && !loading">
          <div class="mb-6">
            <div class="d-flex align-center mb-2">
              <h3 class="text-title-large">Overview</h3>
              <v-tooltip v-if="projectData.description" location="top">
                <template #activator="{ props: tp }">
                  <v-btn
                    v-bind="tp"
                    icon
                    variant="text"
                    size="x-small"
                    class="ml-1"
                    :color="copiedField === 'description' ? 'success' : undefined"
                    @click="copyField(projectData.description, 'description')"
                  >
                    <v-icon size="14">mdi-content-copy</v-icon>
                  </v-btn>
                </template>
                <span>{{ copiedField === 'description' ? 'Copied!' : 'Copy description' }}</span>
              </v-tooltip>
            </div>
            <v-chip :color="statusColor" :style="statusTextStyle" variant="flat" size="small" class="mr-2">{{ projectData.status }}</v-chip>
            <span class="text-body-small text-muted-a11y">
              Created {{ formatDateTime(projectData.created_at) }}
              <template v-if="projectData.completed_at"> | Completed {{ formatDateTime(projectData.completed_at) }}</template>
            </span>
            <p class="mt-2">{{ projectData.description || 'No description provided.' }}</p>

            <SupersededSuccessorNotice
              v-if="projectData.status === 'superseded'"
              :successor-id="projectData.successor_project_id || null"
              @navigate="$emit('close')"
            />
          </div>

          <div class="mb-6">
            <div class="d-flex align-center mb-2">
              <h3 class="text-title-large">Mission</h3>
              <v-tooltip v-if="missionText" location="top">
                <template #activator="{ props: tp }">
                  <v-btn
                    v-bind="tp"
                    icon
                    variant="text"
                    size="x-small"
                    class="ml-1"
                    :color="copiedField === 'mission' ? 'success' : undefined"
                    @click="copyField(missionText, 'mission')"
                  >
                    <v-icon size="14">mdi-content-copy</v-icon>
                  </v-btn>
                </template>
                <span>{{ copiedField === 'mission' ? 'Copied!' : 'Copy mission' }}</span>
              </v-tooltip>
            </div>
            <v-card variant="flat" class="pa-3 smooth-border">
              <pre v-if="missionText" class="text-body-medium text-pre-wrap">{{ missionText }}</pre>
              <p v-else class="text-body-small text-muted-a11y">No data</p>
            </v-card>
          </div>

          <div class="mb-6">
            <h3 class="text-title-large mb-2 d-flex align-center">
              Agents ({{ agents.length }})
              <v-chip v-if="executionModeLabel" size="small" variant="tonal" class="ml-3">
                <img v-if="executionModeIcon.img" :src="executionModeIcon.img" :alt="executionModeLabel" class="giljo-icon-sm mr-1" />
                <v-icon v-else size="small" class="mr-1">{{ executionModeIcon.icon }}</v-icon>
                {{ executionModeLabel }}
              </v-chip>
            </h3>
            <p v-if="!agents.length" class="text-body-small text-muted-a11y">No data</p>
            <div v-else>
              <div
                v-for="agent in agents"
                :key="agent.id"
                class="agent-roster-row smooth-border mb-2 pa-3 rounded"
              >
                <div
                  class="d-flex align-center cursor-pointer"
                  role="button"
                  tabindex="0"
                  :aria-expanded="isAgentExpanded(agent.id)"
                  :aria-label="`Toggle job details for ${agent.agent_display_name}`"
                  @click="toggleAgentExpand(agent.id)"
                  @keydown.enter="toggleAgentExpand(agent.id)"
                >
                  <div
                    class="agent-badge-sq agent-badge-sq--sm mr-2"
                    :style="{ background: hexToRgba(agentTypeColor(agent.agent_name), 0.15), color: agentTypeColor(agent.agent_name) }"
                  >
                    {{ agentTypeBadge(agent.agent_name) }}
                  </div>
                  <span class="font-weight-medium">{{ agent.agent_display_name }}</span>
                  <v-spacer />
                  <span
                    v-if="agent.agent_name"
                    class="agent-tinted-badge mr-2"
                    :style="{ backgroundColor: hexToRgba(agentTypeColor(agent.agent_name), 0.15), color: agentTypeColor(agent.agent_name) }"
                  >{{ agent.agent_name }}</span>
                  <v-chip :color="agentStatusColor(agent.status)" size="x-small" variant="flat" class="mr-2">{{ agent.status }}</v-chip>
                  <v-icon size="small" class="expand-chevron" :class="{ 'expand-chevron--open': isAgentExpanded(agent.id) }">
                    mdi-chevron-down
                  </v-icon>
                </div>
                <v-expand-transition>
                  <div v-if="isAgentExpanded(agent.id)" class="mt-3 pt-3 agent-details-section">
                    <div v-if="agentJobDetail(agent)" class="agent-job-details">
                      <div class="d-flex flex-wrap ga-3 mb-2">
                        <div class="detail-field">
                          <span class="detail-label">Job ID</span>
                          <span class="detail-value text-mono">{{ truncate(agentJobDetail(agent).job_id, 12) }}</span>
                        </div>
                        <div class="detail-field">
                          <span class="detail-label">Status</span>
                          <v-chip :color="agentStatusColor(agentJobDetail(agent).status)" size="x-small" variant="flat">{{ agentJobDetail(agent).status }}</v-chip>
                        </div>
                        <div class="detail-field">
                          <span class="detail-label">Type</span>
                          <span class="detail-value">{{ agentJobDetail(agent).job_type || '-' }}</span>
                        </div>
                        <div v-if="agentJobDetail(agent).created_at" class="detail-field">
                          <span class="detail-label">Created</span>
                          <span class="detail-value">{{ formatDateTime(agentJobDetail(agent).created_at) }}</span>
                        </div>
                        <div v-if="agentJobDetail(agent).completed_at" class="detail-field">
                          <span class="detail-label">Completed</span>
                          <span class="detail-value">{{ formatDateTime(agentJobDetail(agent).completed_at) }}</span>
                        </div>
                      </div>
                      <div v-if="agentJobDetail(agent).result?.summary" class="mt-2">
                        <span class="detail-label">Result Summary</span>
                        <p class="text-body-medium mt-1">{{ agentJobDetail(agent).result.summary }}</p>
                      </div>
                      <div v-if="agentJobDetail(agent).mission" class="mt-2">
                        <span class="detail-label">Assigned Mission</span>
                        <p class="text-body-medium mt-1 mission-text">{{ agentJobDetail(agent).mission }}</p>
                      </div>
                    </div>
                    <p v-else class="text-body-small text-muted-a11y">No job details available.</p>
                  </div>
                </v-expand-transition>
              </div>
            </div>
          </div>

          <div v-if="agents.length" class="mb-6">

            <h3 class="text-title-large mb-2">Agent Messages</h3>
            <v-expansion-panels v-model="expandedAgentPanels" variant="accordion">
              <v-expansion-panel
                v-for="(agent, idx) in agents"
                :key="agent.id"
                :value="idx"
              >
                <v-expansion-panel-title>
                  <div class="d-flex align-center w-100">
                    <div
                      class="agent-badge-sq agent-badge-sq--sm mr-2"
                      :style="{ background: hexToRgba(agentTypeColor(agent.agent_name), 0.15), color: agentTypeColor(agent.agent_name) }"
                    >
                      {{ agentTypeBadge(agent.agent_name) }}
                    </div>
                    <span class="font-weight-medium">{{ agent.agent_display_name }}</span>
                    <v-spacer />
                    <v-chip :color="agentStatusColor(agent.status)" size="x-small" variant="flat" class="mr-2">{{ agent.status }}</v-chip>
                  </div>
                </v-expansion-panel-title>
                <v-expansion-panel-text>
                  <v-progress-linear v-if="agentMessages[agent.id]?.loading" indeterminate />
                  <v-alert v-else-if="agentMessages[agent.id]?.error" type="warning" density="compact" variant="tonal" class="mb-2">
                    Failed to load messages
                  </v-alert>
                  <div v-else-if="agentMessages[agent.id]?.messages?.length">
                    <div v-for="msg in agentMessages[agent.id].messages" :key="msg.id" class="mb-2 pa-2 rounded message-bg">
                      <div class="d-flex justify-space-between align-center">
                        <div class="d-flex align-center">
                          <span class="text-body-small font-weight-bold">{{ msg.from }}</span>
                          <v-chip v-if="msg.direction" size="x-small" :color="msg.direction === 'outbound' ? 'primary' : 'default'" class="ml-2">{{ msg.direction }}</v-chip>
                        </div>
                        <span class="text-body-small text-muted-a11y">{{ formatDateTime(msg.created_at) }}</span>
                      </div>
                      <p class="text-body-medium mt-1">{{ msg.content }}</p>
                    </div>
                  </div>
                  <p v-else class="text-body-small text-muted-a11y">No messages recorded.</p>
                </v-expansion-panel-text>
              </v-expansion-panel>
            </v-expansion-panels>
          </div>

          <div class="mb-6">
            <div class="d-flex align-center mb-2">
              <h3 class="text-title-large">Project Threads</h3>
              <v-spacer />
              <v-btn
                v-if="boundThread"
                size="small"
                variant="text"
                prepend-icon="mdi-open-in-new"
                data-testid="project-comms-open-hub"
                @click="openInHub"
              >Open in Hub</v-btn>
            </div>
            <v-progress-linear v-if="boundThreadLoading" indeterminate color="primary" />
            <v-card
              v-else-if="boundThread"
              variant="flat"
              class="pa-0 smooth-border project-comms-card"
              data-testid="project-comms-timeline"
            >
              <ThreadTimeline :thread-id="boundThread.thread_id" />
            </v-card>
            <p v-else class="text-body-small text-muted-a11y" data-testid="project-comms-empty">
              No project thread yet.
            </p>
          </div>

          <div class="mb-6">
            <h3 class="text-title-large mb-2">360 Memory ({{ memoryEntries.length }} entries)</h3>
            <p v-if="!memoryEntries.length" class="text-body-small text-muted-a11y">No data</p>
            <v-expansion-panels v-else variant="accordion">
              <v-expansion-panel v-for="(entry, i) in memoryEntries" :key="i" :value="i">
                <v-expansion-panel-title>
                  <div class="d-flex align-center w-100 memory-title-row">
                    <v-icon icon="mdi-book-open-page-variant" class="mr-2 flex-shrink-0" size="small" />
                    <span class="font-weight-medium memory-title-text">
                      #{{ entry.sequence ?? i + 1 }} - {{ entry.project_name || 'Memory Entry' }}
                    </span>
                    <v-spacer />
                    <span v-if="entry.timestamp" class="text-body-small text-muted-a11y flex-shrink-0 ml-2">{{ formatDateTime(entry.timestamp) }}</span>
                    <v-tooltip location="top">
                      <template #activator="{ props: tp }">
                        <v-btn
                          v-bind="tp"
                          icon
                          variant="text"
                          size="x-small"
                          class="ml-1 flex-shrink-0"
                          :color="copiedField === `memory-${i}` ? 'success' : undefined"
                          @click.stop="copyMemoryEntry(entry, i)"
                        >
                          <v-icon size="14">mdi-content-copy</v-icon>
                        </v-btn>
                      </template>
                      <span>{{ copiedField === `memory-${i}` ? 'Copied!' : 'Copy memory entry' }}</span>
                    </v-tooltip>
                  </div>
                </v-expansion-panel-title>
                <v-expansion-panel-text>
                  <div v-if="entry.summary" class="mb-3">
                    <h4 class="text-title-small font-weight-bold mb-1">Summary</h4>
                    <div class="text-body-medium">{{ entry.summary }}</div>
                  </div>
                  <div v-if="entry.key_outcomes && entry.key_outcomes.length" class="mb-3">
                    <h4 class="text-title-small font-weight-bold mb-1">Key Outcomes</h4>
                    <v-list density="compact">
                      <v-list-item v-for="(outcome, oi) in entry.key_outcomes" :key="oi" class="px-0">
                        <template #prepend>
                          <v-icon icon="mdi-check-circle" color="success" size="small" class="mr-2" />
                        </template>
                        <v-list-item-title class="text-body-medium">{{ outcome }}</v-list-item-title>
                      </v-list-item>
                    </v-list>
                  </div>
                  <div v-if="entry.decisions_made && entry.decisions_made.length" class="mb-3">
                    <h4 class="text-title-small font-weight-bold mb-1">Decisions Made</h4>
                    <v-list density="compact">
                      <v-list-item v-for="(decision, di) in entry.decisions_made" :key="di" class="px-0">
                        <template #prepend>
                          <v-icon icon="mdi-lightbulb" color="warning" size="small" class="mr-2" />
                        </template>
                        <v-list-item-title class="text-body-medium">{{ decision }}</v-list-item-title>
                      </v-list-item>
                    </v-list>
                  </div>
                  <div v-if="!entry.summary && !entry.key_outcomes?.length && !entry.decisions_made?.length">
                    <p class="text-body-small text-muted-a11y">No detailed content available.</p>
                  </div>
                  <div v-if="entry.entry_type" class="mt-3 pt-2 entry-divider">
                    <span class="text-body-small text-muted-a11y">
                      <strong>Type:</strong> {{ entry.entry_type }}
                      <template v-if="entry.source"> | <strong>Source:</strong> {{ entry.source }}</template>
                    </span>
                  </div>
                </v-expansion-panel-text>
              </v-expansion-panel>
            </v-expansion-panels>
          </div>

          <div class="mb-6">
            <h3 class="text-title-large mb-2">Commits</h3>
            <div v-if="gitCommits.length">
              <div v-for="commit in gitCommits" :key="commit.sha" class="d-flex align-center mb-1 commit-row">
                <span class="text-mono commit-sha mr-3">{{ commit.sha?.slice(0, 8) }}</span>
                <span class="text-body-medium">{{ commitTitle(commit) }}</span>
              </div>
            </div>
            <p v-else class="text-body-small text-muted-a11y">No commits recorded</p>
          </div>
        </template>
      </v-card-text>

      <v-divider />

      <div class="dlg-footer">
        <v-spacer />
        <v-btn variant="elevated" color="primary" aria-label="Close review modal" data-testid="review-close-btn" @click="$emit('close')">
          Close
        </v-btn>
      </div>
    </v-card>
  </v-dialog>
</template>

<script setup>
import { ref, reactive, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useDisplay } from 'vuetify'
import { useClipboard } from '@/composables/useClipboard'
import { useFormatDate } from '@/composables/useFormatDate'
import { getAgentColor } from '@/config/agentColors'
import { hexToRgba } from '@/utils/colorUtils'
import { commitTitle } from '@/utils/gitCommitDisplay'
import api from '@/services/api'
import { useProjectStateStore } from '@/stores/projectStateStore'
import { useProjectBoundThread } from '@/composables/useProjectBoundThread'
import { useCommHubStore } from '@/stores/commHubStore'
import ThreadTimeline from '@/components/hub/ThreadTimeline.vue'
import SupersededSuccessorNotice from './SupersededSuccessorNotice.vue'

const { formatDateTime } = useFormatDate()
const projectStateStore = useProjectStateStore()
const router = useRouter()
const commHub = useCommHubStore()
const { resolveExistingProjectThread } = useProjectBoundThread()

const props = defineProps({
  show: { type: Boolean, required: true },
  projectId: { type: String, default: null },
  productId: { type: String, default: null },
})

const emit = defineEmits(['close'])

const { mobile } = useDisplay()
const isMobile = computed(() => mobile.value)
const { copy: clipboardCopy, copied } = useClipboard()

const copiedField = ref(null)
let copiedTimer = null

function copyField(text, field) {
  if (!text) return
  clipboardCopy(text)
  copiedField.value = field
  clearTimeout(copiedTimer)
  copiedTimer = setTimeout(() => { copiedField.value = null }, 2000)
}

function copyMemoryEntry(entry, i) {
  const parts = []
  if (entry.summary) parts.push(`Summary:\n${entry.summary}`)
  if (entry.key_outcomes?.length) parts.push(`Key Outcomes:\n${entry.key_outcomes.map((o) => `- ${o}`).join('\n')}`)
  if (entry.decisions_made?.length) parts.push(`Decisions Made:\n${entry.decisions_made.map((d) => `- ${d}`).join('\n')}`)
  copyField(parts.join('\n\n') || JSON.stringify(entry, null, 2), `memory-${i}`)
}

const loading = ref(false)
const error = ref(null)
const projectData = ref(null)
const boundThread = ref(null)
const boundThreadLoading = ref(false)
const agents = ref([])
const agentJobs = ref([])
const memoryEntries = ref([])
const agentMessages = reactive({})
const expandedAgentPanels = ref([])
const expandedAgentIds = ref(new Set())

function copyProjectId() {
  if (props.projectId) clipboardCopy(props.projectId)
}

const EXECUTION_MODE_MAP = {
  multi_terminal: { label: 'Multi-Terminal', icon: 'mdi-monitor-multiple', img: null },
  subagent: { label: 'Subagent', icon: 'mdi-connection', img: null },
}

function resolveExecutionModeEntry(mode) {
  if (!mode) return null
  return EXECUTION_MODE_MAP[mode === 'multi_terminal' ? 'multi_terminal' : 'subagent']
}

const executionModeLabel = computed(() => {
  const mode = projectStateStore.getProjectState(props.projectId)?.execution_mode ?? projectData.value?.execution_mode
  return resolveExecutionModeEntry(mode)?.label || ''
})

const executionModeIcon = computed(() => {
  const mode = projectStateStore.getProjectState(props.projectId)?.execution_mode ?? projectData.value?.execution_mode
  return resolveExecutionModeEntry(mode) || { icon: 'mdi-help', img: null }
})

function agentTypeColor(agentName) {
  return getAgentColor(agentName).hex
}

function agentTypeBadge(agentName) {
  return getAgentColor(agentName).badge
}

function isAgentExpanded(agentId) {
  return expandedAgentIds.value.has(agentId)
}

function toggleAgentExpand(agentId) {
  const ids = expandedAgentIds.value
  if (ids.has(agentId)) {
    ids.delete(agentId)
  } else {
    ids.add(agentId)
  }
}

function agentJobDetail(agent) {
  const jobId = agent.job_id || agent.id
  return agentJobs.value.find((j) => j.job_id === jobId) || null
}

const gitCommits = computed(() => {
  const commits = []
  const seen = new Set()
  for (const entry of memoryEntries.value) {
    if (entry.git_commits && Array.isArray(entry.git_commits)) {
      for (const commit of entry.git_commits) {
        if (commit.sha && !seen.has(commit.sha)) {
          seen.add(commit.sha)
          commits.push(commit)
        }
      }
    }
  }
  return commits
})

watch(() => props.show, (open) => {
  if (open && props.projectId) {
    loadReviewData()
    loadBoundThread()
  } else {
    resetState()
  }
})

watch(expandedAgentPanels, (expanded) => {
  if (expanded == null) return
  const indices = Array.isArray(expanded) ? expanded : [expanded]
  for (const idx of indices) {
    const agent = agents.value[idx]
    if (agent) loadAgentMessages(agent)
  }
})

async function loadReviewData() {
  loading.value = true
  error.value = null
  try {
    const res = await api.projects.review(props.projectId)
    const data = res.data
    projectData.value = data.project
    agents.value = data.project?.agents || []
    agentJobs.value = data.agent_jobs || []
    memoryEntries.value = data.memory_entries || []
  } catch (err) {
    console.error('[ProjectReviewModal] Failed to load:', err)
    error.value = err.response?.data?.message || err.message || 'Failed to load project data'
  } finally {
    loading.value = false
  }
}

async function loadBoundThread() {
  if (!props.projectId) return
  boundThreadLoading.value = true
  try {
    const t = await resolveExistingProjectThread(props.projectId)
    boundThread.value = t
    if (t) {
      await commHub.loadThread(t.thread_id)
      await commHub.loadParticipants(t.thread_id)
    }
  } catch (err) {
    console.error('[ProjectReviewModal] bound thread load failed:', err)
    boundThread.value = null
  } finally {
    boundThreadLoading.value = false
  }
}

function openInHub() {
  if (!boundThread.value) return
  router.push({ name: 'Hub', query: { thread: boundThread.value.thread_id, tab: 'project' } })
  emit('close')
}

async function loadAgentMessages(agent) {
  const key = agent.id
  if (agentMessages[key]) return
  if (!agent.job_id) {
    agentMessages[key] = { loading: false, messages: [], error: true }
    return
  }
  agentMessages[key] = { loading: true, messages: [], error: false }
  try {
    const res = await api.agentJobs.messages(agent.job_id)
    agentMessages[key] = { loading: false, messages: (res.data?.messages || []).slice(0, 20), error: false }
  } catch (err) {
    console.error(`[ProjectReviewModal] Failed to load messages for job ${agent.job_id}:`, err)
    agentMessages[key] = { loading: false, messages: [], error: true }
  }
}

function resetState() {
  projectData.value = null
  boundThread.value = null
  boundThreadLoading.value = false
  agents.value = []
  agentJobs.value = []
  memoryEntries.value = []
  Object.keys(agentMessages).forEach((k) => delete agentMessages[k])
  expandedAgentPanels.value = []
  expandedAgentIds.value = new Set()
  error.value = null
}

const missionText = computed(() => {
  const m = projectData.value?.mission
  if (!m) return ''
  if (typeof m === 'string') return m
  return m.mission_statement || m.objective || JSON.stringify(m, null, 2)
})

const statusColor = computed(() => {
  const s = projectData.value?.status
  if (s === 'completed') return 'success'
  if (s === 'active') return 'white'
  if (s === 'terminated') return 'warning'
  if (s === 'cancelled') return 'grey'
  if (s === 'superseded') return 'grey'
  return 'primary'
})

const statusTextStyle = computed(() => {
  if (projectData.value?.status === 'active') return { color: 'var(--color-text-dark)' }
  return {}
})

function agentStatusColor(status) {
  if (status === 'complete' || status === 'completed') return 'success'
  if (status === 'decommissioned') return 'grey'
  if (status === 'working') return 'primary'
  if (status === 'waiting') return 'info'
  return 'default'
}


function truncate(text, maxLen) {
  if (!text) return ''
  return text.length > maxLen ? `${text.slice(0, maxLen)}...` : text
}
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

.review-project-name {
  color: $color-brand-yellow;
  font-weight: 600;
}
.review-project-id {
  font-family: monospace;
  cursor: pointer;
  user-select: all;
}
.review-project-id:hover {
  text-decoration: underline;
}
.giljo-icon-sm {
  width: 16px;
  height: 16px;
}
.message-bg {
  background: rgba(var(--v-theme-on-surface), 0.03);
}
.project-comms-card {
  // Bound the embedded read-only timeline so it scrolls inside the modal
  // instead of stretching the dialog body.
  display: flex;
  max-height: 360px;
  overflow: hidden;
}
.entry-divider {
  border-top: 1px solid rgba(var(--v-theme-on-surface), 0.12);
}
.cursor-pointer {
  cursor: pointer;
}
.agent-roster-row {
  background: rgba(var(--v-theme-on-surface), 0.02);
}
.expand-chevron {
  transition: transform 0.2s ease;
}
.expand-chevron--open {
  transform: rotate(180deg);
}
.agent-details-section {
  border-top: 1px solid rgba(var(--v-theme-on-surface), 0.08);
}
.detail-field {
  display: flex;
  flex-direction: column;
  min-width: 100px;
}
.detail-label {
  font-size: 0.7rem;
  color: $color-text-muted;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 2px;
}
.detail-value {
  font-size: 0.875rem;
}
.text-mono {
  font-family: monospace;
}
.mission-text {
  white-space: pre-line;
  color: $color-text-muted;
  font-size: 0.8rem;
  line-height: 1.4;
}
.commit-row {
  padding: 4px 8px;
  border-radius: 4px;
}
.commit-row:hover {
  background: rgba(var(--v-theme-on-surface), 0.04);
}
.commit-sha {
  font-size: 0.8rem;
  color: $color-brand-yellow;
  min-width: 80px;
}
.memory-title-row {
  overflow: visible;
}
.memory-title-text {
  white-space: normal;
  overflow: visible;
  text-overflow: unset;
  min-width: 0;
  word-break: break-word;
}

</style>
