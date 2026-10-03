<template>
  <v-card
    class="jb-card smooth-border"
    :class="{ 'jb-card--folded': folded, 'jb-card--attn': folded && needsYou, 'jb-card--member': !!chainCtx }"
    :style="{ '--jb-edge': edgeColor }"
    data-testid="jobs-board-card"
    :data-lifecycle="sectionLabel"
  >
    <v-card-text class="jb-card-body">
      <div class="jb-head" data-testid="jb-head">
        <span class="jb-tax-pill" data-testid="jb-tax-pill" :style="taxonomyStyle">{{ project.taxonomy_alias }}</span>
        <v-tooltip location="bottom" open-delay="150">
          <template #activator="{ props: tooltipProps }">
            <h2 v-bind="tooltipProps" class="jb-title" data-testid="jb-title">
              {{ project.name }}
            </h2>
          </template>
          <div data-testid="jb-title-tooltip">{{ project.name }}</div>
        </v-tooltip>
        <button
          type="button"
          class="jb-fold-btn"
          :aria-expanded="!folded"
          :aria-label="folded ? 'Show details' : 'Hide details'"
          :title="folded ? 'Show details' : 'Hide details'"
          data-testid="jb-fold-btn"
          @click="toggleFold"
        >
          <v-icon size="14">{{ folded ? 'mdi-chevron-right' : 'mdi-chevron-down' }}</v-icon>
        </button>
      </div>

      <div class="jb-pills" data-testid="jb-pill-row">
        <span
          class="jb-status-pill"
          :class="{ 'live-pill': lifecycleLive }"
          :data-testid="needsInput ? 'jb-lifecycle-pill' : 'jb-status-pill'"
          :style="{ backgroundColor: hexToRgba(lifecyclePillColor, 0.15), color: lifecyclePillColor }"
        >
          {{ sectionLabel }}<LiveDots v-if="lifecycleLive" />
        </span>
        <v-tooltip v-if="needsInput" location="bottom" open-delay="150">
          <template #activator="{ props: tooltipProps }">
            <button
              v-if="needsInput.kind === 'decision'"
              v-bind="tooltipProps"
              type="button"
              class="jb-status-pill jb-status-pill--decision"
              aria-label="Open Jobs detail to decide"
              data-testid="jb-status-pill"
              @click="emit('open-detail', project)"
            >
              {{ needsInput.text }}
            </button>
            <span
              v-else
              v-bind="tooltipProps"
              class="jb-status-pill jb-status-pill--hint"
              data-testid="jb-status-pill"
              :style="{ backgroundColor: hexToRgba(edgeColor, 0.15), color: edgeColor }"
            >
              {{ needsInput.text }}
            </span>
          </template>
          <div class="jb-pill-hint" data-testid="jb-status-pill-hint">{{ needsInput.hint }}</div>
        </v-tooltip>
      </div>

      <template v-if="!folded">
      <div class="jb-meta" data-testid="jb-meta">
        <span class="jb-meta-text">{{ metaLine }}</span>
        <JobsBoardMetaIcons
          :git-enabled="gitEnabled"
          :integrations-resolved="integrationsResolved"
          :execution-mode="factualMode"
        />
      </div>

      <div v-if="showGateNote" class="jb-gate-note" data-testid="jb-gate-note">
        <v-icon class="jb-gate-icon" size="14">mdi-hand-back-right-outline</v-icon>
        <div>
          <strong>Your launch required</strong>
          <span>
            Headless self-advance is off, so agents stop at the staging gate and wait for you.
            Turn it on in
            <router-link :to="{ path: '/tools', query: { tab: 'agents' } }" data-testid="jb-gate-note-link">
              Tools → Agents
            </router-link>
            to let a trusted agent implement on its own.
          </span>
        </div>
      </div>

      <div v-if="stagingLayout" class="jb-stats jb-stats--3col">
        <div class="jb-stat">
          <span class="jb-stat-k">Mode</span>
          <span class="jb-stat-v jb-stat-word" :class="{ 'jb-stat-warn': !stagingModeLabel }" data-testid="jb-stat-mode">
            {{ stagingModeLabel || 'not picked' }}
          </span>
        </div>
        <div class="jb-stat">
          <span class="jb-stat-k">Harness</span>
          <span class="jb-stat-v jb-stat-word" data-testid="jb-stat-harness">
            <HarnessChip v-if="orchestratorHarness" :harness="orchestratorHarness" />
            <span v-else class="jb-stat-muted">—</span>
          </span>
        </div>
        <div class="jb-stat">
          <span class="jb-stat-k">Phases</span>
          <span class="jb-stat-v" :class="{ 'jb-stat-muted': !phaseCount }" data-testid="jb-stat-phases">
            {{ phaseCount || '—' }}
          </span>
        </div>
      </div>
      <div v-else class="jb-stats">
        <div class="jb-stat">
          <span class="jb-stat-k">Steps</span>
          <span class="jb-stat-v" data-testid="jb-stat-steps">
            <template v-if="steps.hasSteps">{{ steps.completed }}<span class="jb-stat-sub">/{{ steps.total }}</span></template>
            <span v-else class="jb-stat-muted">—</span>
          </span>
        </div>
        <div class="jb-stat">
          <span class="jb-stat-k">Agents</span>
          <span class="jb-stat-v" data-testid="jb-stat-agents">{{ agents.length }}</span>
        </div>
        <div class="jb-stat">
          <span class="jb-stat-k">Waiting</span>
          <span class="jb-stat-v" :class="waiting > 0 ? 'jb-stat-warn' : 'jb-stat-muted'" data-testid="jb-stat-waiting">
            {{ waiting }}
          </span>
        </div>
        <div class="jb-stat">
          <span class="jb-stat-k">Duration</span>
          <span class="jb-stat-v jb-stat-muted" data-testid="jb-stat-duration">{{ durationLabel }}</span>
        </div>
      </div>

      <JobsBoardSummaryRows
        :project="project"
        :mission="missionText"
        :mission-state="missionState"
        :chain-member="!!chainCtx"
        @edit-description="(p) => emit('edit-description', p)"
      />
      <button
        type="button"
        class="jb-details-btn"
        :aria-expanded="detailsOpen"
        data-testid="jb-details-btn"
        @click="detailsOpen = !detailsOpen"
      >
        <v-icon size="14" class="jb-details-chev" :class="{ 'jb-details-chev--open': detailsOpen }">mdi-chevron-right</v-icon>
        Details
      </button>
      <JobsBoardCardDrawer
        v-if="detailsOpen"
        :project="project"
        :agents="sortedAgents"
        :mission="missionText"
        :mission-state="missionState"
        :launched="!stagingLayout"
        :chain-member="!!chainCtx"
        @edit-description="(p) => emit('edit-description', p)"
        @agent-role="(a) => emit('agent-role', a)"
        @agent-mission-edit="(a) => emit('agent-mission-edit', a)"
      />

      <div class="jb-agents" data-testid="jb-agents-list">
        <JobsBoardAgentRow
          v-for="agent in sortedAgents"
          :key="agent.agent_id || agent.job_id || agent.id"
          :agent="agent"
          :now="now"
          :interactive="rowsInteractive"
          :show-copy="rowsInteractive && shouldShowCopyButton(agent)"
          :play-faded="isPlayButtonFaded(agent)"
          :play-tooltip="playButtonTooltip(agent)"
          :can-replay="canReplay(agent)"
          @play="handlePlay"
          @replay="handleReplay"
          @messages="(a) => emit('agent-messages', a, project)"
          @agent-role="(a) => emit('agent-role', a)"
          @agent-job="(a) => emit('agent-job', a)"
          @steps="(a) => emit('steps', a)"
        />
      </div>

      <JobsBoardCardFooter
        :project="project"
        :section-label="sectionLabel"
        :show-staging="showStaging"
        @open-detail="(p) => emit('open-detail', p)"
        @open-hub="(p) => emit('open-hub', p)"
        @changed="(p) => emit('changed', p)"
        @review="(p) => emit('review', p)"
      />
      </template>

      <JobsBoardCardSummary
        v-else
        :agents="sortedAgents"
        :steps="steps"
        :waiting="waiting"
        :duration="durationLabel"
      >
        <template #action>
          <JobsBoardCardFooter
            :project="project"
            :section-label="sectionLabel"
            :show-staging="showStaging"
            compact
            @open-detail="(p) => emit('open-detail', p)"
            @open-hub="(p) => emit('open-hub', p)"
            @changed="(p) => emit('changed', p)"
            @review="(p) => emit('review', p)"
          />
        </template>
      </JobsBoardCardSummary>
    </v-card-text>
  </v-card>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { hexToRgba } from '@/utils/colorUtils'
import { jobsSectionLabelFor, JOBS_SECTION_LABELS } from '@/utils/jobsSectionLabel'
import { jobsBoardLifecycleColor, needsInputColor } from '@/utils/jobsBoardLifecycle'
import { TEXT_SECONDARY } from '@/config/colorTokens'
import { needsInputOwner } from '@/utils/jobStatusWord'
import { orderAgentsForDisplay } from '@/utils/agentDisplayOrder'
import { taxonomyBadgeStyle, resolveTaxonomyColor } from '@/utils/taxonomyBadge'
import { BOARD_DENSITIES } from '@/composables/useBoardDensity'
import { aggregateSteps, aggregateWaiting, projectDurationSeconds, jobsBoardMetaLine } from '@/utils/jobsBoardCardStats'
import { formatDurationSeconds } from '@/utils/durationFormat'
import { useClipboard } from '@/composables/useClipboard'
import { usePlayButton } from '@/composables/usePlayButton'
import { isProjectLaunched } from '@/composables/useProjectStageControls'
import { useProjectStateStore } from '@/stores/projectStateStore'
import JobsBoardAgentRow from '@/components/projects/JobsBoardAgentRow.vue'
import JobsBoardCardFooter from '@/components/projects/JobsBoardCardFooter.vue'
import JobsBoardCardSummary from '@/components/projects/JobsBoardCardSummary.vue'
import JobsBoardSummaryRows from '@/components/projects/JobsBoardSummaryRows.vue'
import JobsBoardCardDrawer from '@/components/projects/JobsBoardCardDrawer.vue'
import JobsBoardMetaIcons from '@/components/projects/JobsBoardMetaIcons.vue'
import { isSubagentExecutionMode } from '@/composables/useExecutionMode'
import { isOrchestrator } from '@/utils/agentDisplay'
import HarnessChip from '@/components/projects/project-tabs/HarnessChip.vue'
import LiveDots from '@/components/projects/LiveDots.vue'

const props = defineProps({
  project: {
    type: Object,
    required: true,
  },
  agents: {
    type: Array,
    default: () => [],
  },
  now: {
    type: Number,
    required: true,
  },
  headlessAllowed: {
    type: Boolean,
    default: null,
  },
  showStaging: {
    type: Boolean,
    default: true,
  },
  chainCtx: {
    type: Object,
    default: null,
  },
  density: {
    type: String,
    default: BOARD_DENSITIES.DETAILED,
  },
  gitEnabled: {
    type: Boolean,
    default: false,
  },
  integrationsResolved: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits([
  'open-detail',
  'open-hub',
  'changed',
  'agent-messages',
  'agent-role',
  'agent-job',
  'edit-description',
  'review',
  'steps',
  'agent-mission-edit',
])

const sectionLabel = computed(() => jobsSectionLabelFor(props.project, props.agents))
const LIVE_LIFECYCLES = new Set([JOBS_SECTION_LABELS.PLANNING, JOBS_SECTION_LABELS.IMPLEMENTING])
const lifecycleLive = computed(() => LIVE_LIFECYCLES.has(sectionLabel.value))
const NEEDS_LABELS = [JOBS_SECTION_LABELS.NEEDS_DECISION, JOBS_SECTION_LABELS.NEEDS_ATTENTION]
const needsInput = computed(() =>
  NEEDS_LABELS.includes(sectionLabel.value) ? needsInputOwner(props.agents) : null,
)
const edgeColor = computed(() =>
  needsInput.value ? needsInputColor(needsInput.value.kind) : jobsBoardLifecycleColor(sectionLabel.value),
)
const lifecyclePillColor = computed(() => (needsInput.value ? TEXT_SECONDARY : edgeColor.value))
const showGateNote = computed(
  () => sectionLabel.value === JOBS_SECTION_LABELS.STAGED && props.headlessAllowed === false,
)
const sortedAgents = computed(() => orderAgentsForDisplay(props.agents))
const taxonomyStyle = computed(() =>
  taxonomyBadgeStyle(
    resolveTaxonomyColor({
      abbreviation: props.project?.project_type?.abbreviation,
      alias: props.project?.taxonomy_alias,
      color: props.project?.project_type?.color,
    }),
  ),
)
const needsYou = computed(
  () => NEEDS_LABELS.includes(sectionLabel.value) || sectionLabel.value === JOBS_SECTION_LABELS.STAGED,
)
function foldByRule() {
  return props.density === BOARD_DENSITIES.COMPACT
}
const folded = ref(foldByRule())
watch(() => props.density, () => {
  folded.value = foldByRule()
})
function toggleFold() {
  folded.value = !folded.value
}
const STAGING_LABELS = new Set([JOBS_SECTION_LABELS.ACTIVATED, JOBS_SECTION_LABELS.PLANNING, JOBS_SECTION_LABELS.STAGED])
const stagingLayout = computed(() => STAGING_LABELS.has(sectionLabel.value))
const missionText = computed(
  () => projectStateStore.getProjectState(props.project?.id)?.mission || props.project?.mission || '',
)
const factualMode = computed(() => {
  if (sectionLabel.value === JOBS_SECTION_LABELS.ACTIVATED) return ''
  return props.project?.execution_mode || ''
})
const stagingModeLabel = computed(() => {
  if (!factualMode.value) return ''
  return isSubagentExecutionMode(factualMode.value) ? 'Subagent' : 'Multi-terminal'
})
const missionState = computed(() => {
  if (sectionLabel.value === JOBS_SECTION_LABELS.PLANNING) return 'writing'
  return missionText.value ? 'written' : 'none'
})
const detailsOpen = ref(false)
const orchestratorHarness = computed(() => props.agents.find(isOrchestrator)?.detected_harness || null)
const phaseCount = computed(
  () => new Set(props.agents.map((a) => a?.phase).filter((phase) => typeof phase === 'number')).size,
)
const steps = computed(() => aggregateSteps(props.agents))
const waiting = computed(() => aggregateWaiting(props.agents))
const durationLabel = computed(() => formatDurationSeconds(projectDurationSeconds(props.project, props.now)))
const metaLine = computed(() => jobsBoardMetaLine(props.project, sectionLabel.value, props.now))

const projectStateStore = useProjectStateStore()
const { copy: clipboardCopy } = useClipboard()
const rowsInteractive = computed(() =>
  isProjectLaunched(props.project, projectStateStore.getProjectState(props.project?.id)),
)
const { shouldShowCopyButton, isPlayButtonFaded, playButtonTooltip, canReplay, handleReplay, handlePlay } = usePlayButton(
  computed(() => props.project),
  (pid) => projectStateStore.getProjectState(pid),
  clipboardCopy,
  computed(() => props.chainCtx),
)
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

.jb-card {
  position: relative;
  height: 100%;
  box-shadow:
    inset 0 0 0 1px var(--smooth-border-color, rgba(255, 255, 255, 0.1)),
    inset 3px 0 0 0 var(--jb-edge, $color-text-secondary);
  transition: box-shadow 0.18s, transform 0.18s;

  &:hover {
    transform: translateY(-2px);
  }
}

.jb-card-body {
  padding: 16px 18px 14px !important;
}

.jb-head {
  display: flex;
  align-items: flex-start;
  gap: $spacing-snug;
  margin-bottom: 3px;
}

// FE-9683: every status pill on its own row, centered under the title.
.jb-pills {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 6px;
  margin: 4px 0 6px;
}

.jb-tax-pill {
  flex: none;
  font-size: 0.67rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  padding: 3px $spacing-snug;
  border-radius: $border-radius-pill;
  font-family: $typography-font-mono;
}

.jb-title {
  flex: 1;
  font-size: 1.02rem;
  font-weight: 600;
  color: $color-brand-yellow;
  margin: 0;
  min-width: 0;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  cursor: help;
}

.jb-status-pill--hint {
  cursor: help;
}

.jb-pill-hint {
  max-width: 280px;
  line-height: 1.45;
}

.jb-fold-btn {
  flex: none;
  align-self: center;
  width: 22px;
  height: 22px;
  display: grid;
  place-items: center;
  background: none;
  border: 1px solid $color-border-secondary;
  border-radius: $border-radius-sharp;
  // FE-9683: clickable controls share the Jobs detail link colour.
  color: $color-text-tertiary;
  cursor: pointer;
  padding: 0;

  &:hover,
  &:focus-visible {
    color: $color-brand-yellow;
    border-color: $color-brand-yellow;
  }
}

.jb-card--folded {
  .jb-head {
    margin-bottom: 0;
  }

  .jb-pills {
    margin-bottom: 0;
  }

  .jb-title {
    -webkit-line-clamp: 1;
  }

  &:hover {
    transform: none;
  }
}

// FE-9682 V1: inside a chain member the card sits under the step label in a
// flex column, so it takes the room that is left instead of the member's full
// height (which pushed it 26 px past its frame).
.jb-card--member {
  height: auto;
  flex: 1 1 auto;
}

.jb-card--attn {
  box-shadow:
    inset 0 0 0 1px color-mix(in srgb, var(--jb-edge, #{$color-text-secondary}) 45%, transparent),
    inset 3px 0 0 0 var(--jb-edge, $color-text-secondary);
}

.jb-status-pill {
  flex: none;
  font-size: 0.67rem;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: $border-radius-pill;
  white-space: nowrap;
  border: 0;
  font-family: inherit;
  line-height: 1.4;
}

// FE-9683: the one pill that is a door. Solid warning fill with navy ink,
// so it reads apart from the faded status pills around it.
.jb-status-pill--decision {
  background: $color-status-warning;
  color: $color-background-primary;
  cursor: pointer;

  &:hover,
  &:focus-visible {
    background: $color-brand-yellow;
  }
}

.jb-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  color: $color-text-secondary;
  font-size: 0.71rem;
  margin: 0 0 12px;
  font-family: $typography-font-mono;
  min-width: 0;
}

.jb-meta-text {
  min-width: 0;
}

.jb-details-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: none;
  border: 0;
  color: $color-text-tertiary;
  font: inherit;
  font-size: 0.72rem;
  font-weight: 500;
  cursor: pointer;
  padding: 2px 6px 2px 2px;
  border-radius: $border-radius-sharp;
  margin: 0 0 10px;

  &:hover,
  &:focus-visible {
    color: $color-brand-yellow;
  }

  &[aria-expanded='true'] {
    color: $color-text-tertiary;
  }
}

.jb-details-chev {
  transition: transform 0.2s;

  &--open {
    transform: rotate(90deg);
  }
}

.jb-gate-note {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin: 0 0 12px;
  padding: $spacing-snug 11px;
  border-radius: $border-radius-default;
  background: rgba($color-status-warning, 0.09);
  border: 1px solid rgba($color-status-warning, 0.32);
  font-size: 0.72rem;
  line-height: 1.45;

  .jb-gate-icon {
    flex: none;
    color: $color-status-warning;
    margin-top: 1px;
  }

  strong {
    display: block;
    color: $color-status-warning;
    font-weight: 600;
    font-size: 0.74rem;
    margin-bottom: 1px;
  }

  span {
    color: $color-text-tertiary;
  }

  a {
    color: $color-brand-yellow;
    text-decoration: none;
    border-bottom: 1px dotted currentColor;
  }
}

.jb-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 6px;
  padding: $spacing-snug 0;
  margin-bottom: 10px;
  border-top: 1px solid $color-border-tertiary;
  border-bottom: 1px solid $color-border-tertiary;

  &--3col {
    grid-template-columns: repeat(3, 1fr);
  }
}

.jb-stat {
  text-align: center;
}

.jb-stat-k {
  display: block;
  font-size: 0.57rem;
  letter-spacing: 0.07em;
  text-transform: uppercase;
  color: $color-text-secondary;
  margin-bottom: 2px;
}

.jb-stat-v {
  display: block;
  font-size: 1.02rem;
  font-weight: 600;
  line-height: 1.1;

  .jb-stat-sub {
    color: $color-text-secondary;
    font-size: 0.75rem;
  }
}

.jb-stat-warn {
  color: $color-text-highlight;
}

.jb-stat-muted {
  color: $color-text-secondary;
  font-size: 0.85rem;
}

.jb-stat-word {
  font-size: 0.8rem;
  font-weight: 500;
  color: $color-text-tertiary;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.jb-agents {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin-bottom: 13px;
}
</style>
