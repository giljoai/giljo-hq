<template>
  <v-dialog :model-value="modelValue" max-width="940" scrollable @update:model-value="emit('update:modelValue', $event)">
    <v-card class="jb-modal-card smooth-border" data-testid="jb-detail-modal">
      <div class="dlg-header">
        <span v-if="project?.taxonomy_alias" class="jb-modal-tax-pill">{{ project.taxonomy_alias }}</span>
        <span class="dlg-title">{{ project?.name }}</span>
        <v-btn
          icon
          variant="text"
          size="small"
          class="dlg-close"
          aria-label="Close dialog"
          data-testid="jb-detail-close"
          @click="emit('update:modelValue', false)"
        >
          <v-icon icon="mdi-close" size="18" />
        </v-btn>
      </div>

      <v-card-text class="jb-modal-body">
        <ProjectStatusBanner
          v-if="banner"
          v-bind="banner"
          @open-closeout-modal="emit('open-closeout')"
          @open-decision-modal="emit('open-decision')"
          @dismiss-orch-unlocked="emit('dismiss-orch-unlocked')"
          @retry-memory-poll="emit('retry-memory-poll')"
          @close-without-summary="(reason) => emit('close-without-summary', reason)"
        />

        <div v-if="executionOrderPhases" class="jb-order" data-testid="execution-order-bar">
          <ExecutionOrderBar :phases="executionOrderPhases" />
        </div>

        <div class="jb-table-scroll">
          <table class="jb-table" data-testid="jb-detail-table">
            <thead>
              <tr>
                <th></th>
                <th>Agent</th>
                <th>Identifiers</th>
                <th>Steps</th>
                <th>Duration</th>
                <th>Status</th>
                <th>Msgs</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="agent in agents" :key="agent.agent_id || agent.job_id" data-testid="jb-detail-row">
                <td><span class="agent-badge-sq" :class="{ 'live-badge': isLiveStatusWord(jobStatusWord(agent)) }" :style="getAgentBadgeStyle(getAgentColorKey(agent))">{{ getAgentInitials(getPrimaryAgentLabel(agent)) }}</span></td>
                <td>
                  <span class="jb-nm">{{ getPrimaryAgentLabel(agent) }}</span><br />
                  <span class="jb-role">{{ getAgentRoleLabel(agent) }}</span>
                </td>
                <td class="jb-idcell">
                  <span class="jb-idlabel">Agent ID</span>
                  <span class="jb-uuid" data-testid="jb-detail-agent-id">{{ agent.agent_id || '—' }}</span>
                  <button
                    v-if="agent.agent_id"
                    class="jb-copy-btn"
                    :class="{ 'jb-copy-btn--done': copiedField === agentCopyKey(agent) }"
                    type="button"
                    :title="`Copy agent ID`"
                    :aria-label="`Copy agent ID`"
                    data-testid="jb-detail-copy-agent"
                    @click="handleCopy(agentCopyKey(agent), agent.agent_id)"
                  >
                    <v-icon v-if="copiedField === agentCopyKey(agent)" size="14">mdi-check</v-icon>
                    <v-icon v-else size="14">mdi-content-copy</v-icon>
                  </button>
                  <br />
                  <span class="jb-idlabel jb-idlabel--second">Job ID</span>
                  <span class="jb-uuid" data-testid="jb-detail-job-id">{{ agent.job_id || agent.id || '—' }}</span>
                  <button
                    v-if="agent.job_id || agent.id"
                    class="jb-copy-btn"
                    :class="{ 'jb-copy-btn--done': copiedField === jobCopyKey(agent) }"
                    type="button"
                    :title="`Copy job ID`"
                    :aria-label="`Copy job ID`"
                    data-testid="jb-detail-copy-job"
                    @click="handleCopy(jobCopyKey(agent), agent.job_id || agent.id)"
                  >
                    <v-icon v-if="copiedField === jobCopyKey(agent)" size="14">mdi-check</v-icon>
                    <v-icon v-else size="14">mdi-content-copy</v-icon>
                  </button>
                </td>
                <td>
                  <template v-if="agent.steps && typeof agent.steps.completed === 'number' && typeof agent.steps.total === 'number'">
                    {{ agent.steps.completed }}/{{ agent.steps.total }}
                  </template>
                  <template v-else>—</template>
                </td>
                <td>{{ formatAgentDuration(agent, now) }}</td>
                <td :style="{ color: getStatusColor(agent.status, agent.block_reason) }">
                  {{ getStatusLabel(agent.status, agent.block_reason) }}<LiveDots v-if="isLiveStatusWord(jobStatusWord(agent))" />
                </td>
                <td>
                  <span class="msg-badge" :class="(agent.messages_waiting_count ?? 0) === 0 ? 'zero' : 'has-msgs'">
                    {{ agent.messages_waiting_count ?? 0 }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="readyForReview" class="jb-review-strip" data-testid="jb-review-strip">
          <p><strong>All agents closed.</strong> Review and close it here. Once reviewed, this project leaves the board.</p>
          <span class="jb-foot-spacer" />
          <v-btn
            class="jb-btn jb-btn-review"
            size="small"
            variant="flat"
            data-testid="jb-review-strip-btn"
            @click="emit('open-closeout')"
          >
            Review and close
          </v-btn>
        </div>

        <MessageComposer
          v-if="project"
          class="jb-composer"
          :project-id="project.id"
          :chain-mode="Boolean(chainCtx)"
          :conductor-agent-id="chainCtx?.conductor?.agentId || ''"
          :chain-run-id="chainCtx?.runId || ''"
          :orchestrator-agent-id="orchestratorAgentId"
        />
      </v-card-text>
    </v-card>
  </v-dialog>
</template>

<script setup>
import { computed, ref } from 'vue'
import { getStatusLabel, getStatusColor } from '@/utils/statusConfig'
import { jobStatusWord, isLiveStatusWord } from '@/utils/jobStatusWord'
import LiveDots from './LiveDots.vue'
import { getAgentBadgeStyle } from '@/utils/colorUtils'
import { getAgentColorKey, getAgentInitials } from '@/config/agentColors'
import { getPrimaryAgentLabel, getAgentRoleLabel } from '@/utils/agentDisplay'
import { formatAgentDuration } from '@/utils/durationFormat'
import { isReadyForReview } from '@/utils/jobsSectionLabel'
import { useClipboard } from '@/composables/useClipboard'
import { isOrchestrator } from '@/utils/agentDisplay'
import { buildExecutionOrderPhases } from '@/utils/executionOrderPhases'
import MessageComposer from '@/components/projects/MessageComposer.vue'
import ExecutionOrderBar from '@/components/projects/ExecutionOrderBar.vue'
import ProjectStatusBanner from '@/components/projects/project-tabs/ProjectStatusBanner.vue'

const props = defineProps({
  modelValue: {
    type: Boolean,
    default: false,
  },
  project: {
    type: Object,
    default: null,
  },
  agents: {
    type: Array,
    default: () => [],
  },
  now: {
    type: Number,
    required: true,
  },
  chainCtx: {
    type: Object,
    default: null,
  },
  banner: {
    type: Object,
    default: null,
  },
})

const orchestratorAgentId = computed(() => (props.agents || []).find(isOrchestrator)?.agent_id || '')
const executionOrderPhases = computed(() => buildExecutionOrderPhases(props.agents, props.project?.execution_mode))

const readyForReview = computed(() => isReadyForReview(props.project, props.agents))

const emit = defineEmits([
  'update:modelValue',
  'open-closeout',
  'open-decision',
  'dismiss-orch-unlocked',
  'retry-memory-poll',
  'close-without-summary',
])

const { copy: clipboardCopy } = useClipboard()
const copiedField = ref(null)
let copiedTimer = null

function agentCopyKey(agent) {
  return `${agent.agent_id || agent.job_id}-agent`
}
function jobCopyKey(agent) {
  return `${agent.agent_id || agent.job_id}-job`
}

async function handleCopy(field, value) {
  if (!value) return
  await clipboardCopy(value)
  copiedField.value = field
  clearTimeout(copiedTimer)
  copiedTimer = setTimeout(() => {
    copiedField.value = null
  }, 2000)
}
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

.jb-modal-card {
  background: rgb(var(--v-theme-surface));
}

.jb-modal-tax-pill {
  font-size: 0.67rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  padding: 3px $spacing-snug;
  border-radius: $border-radius-pill;
  background: rgba($color-accent-success, 0.15);
  color: $color-accent-success;
  font-family: $typography-font-mono;
  margin-right: 8px;
}

.jb-modal-body {
  padding: 8px 20px 20px !important;
}

.jb-order {
  margin-bottom: 10px;
}

.jb-composer {
  margin-top: 16px;
}

.jb-table-scroll {
  overflow-x: auto;
}

.jb-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.78rem;

  th {
    text-align: left;
    font-size: 0.58rem;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    color: $color-text-secondary;
    font-weight: 500;
    padding: 10px 8px;
    border-bottom: 1px solid $color-border-secondary;
  }

  td {
    padding: 11px 8px;
    border-bottom: 1px solid $color-border-tertiary;
    vertical-align: middle;
  }
}

.jb-nm {
  font-weight: 600;
  color: $color-text-primary;
}

.jb-role {
  font-size: 0.67rem;
  color: $color-text-secondary;
}

.jb-idcell {
  white-space: nowrap;
}

.jb-idlabel {
  display: block;
  font-size: 0.55rem;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: $color-text-secondary;
  margin-bottom: 1px;

  &--second {
    margin-top: $spacing-tight;
  }
}

.jb-uuid {
  font-family: $typography-font-mono;
  font-size: 0.67rem;
  color: $color-text-tertiary;
  white-space: nowrap;
}

.jb-copy-btn {
  background: none;
  border: 0;
  color: $color-text-secondary;
  cursor: pointer;
  font-size: 0.72rem;
  padding: 2px $spacing-tight;
  border-radius: $border-radius-sharp;
  margin-left: $spacing-tight;
  vertical-align: middle;
  display: inline-flex;
  align-items: center;

  &:hover {
    color: $color-brand-yellow;
    background: rgba(255, 255, 255, 0.07);
  }

  &--done {
    color: $color-accent-success;
  }
}

.jb-review-strip {
  margin-top: 16px;
  padding: 13px 15px;
  border-radius: $border-radius-md;
  background: rgba($color-accent-success, 0.09);
  border: 1px solid rgba($color-accent-success, 0.35);
  display: flex;
  align-items: center;
  gap: 12px;

  p {
    margin: 0;
    font-size: 0.8rem;
    color: $color-text-tertiary;
  }

  strong {
    color: $color-accent-success;
  }
}

.jb-foot-spacer {
  margin-left: auto;
}

.jb-btn-review {
  background: $color-accent-success;
  color: $color-on-yellow-ink;
  font-size: 0.76rem;
  font-weight: 600;
  text-transform: none;
}
</style>
