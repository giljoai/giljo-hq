<template>
  <v-card
    class="jb-card smooth-border"
    :style="{ '--jb-edge': edgeColor }"
    data-testid="jobs-board-card"
    :data-lifecycle="sectionLabel"
  >
    <v-card-text class="jb-card-body">
      <div class="jb-head">
        <button
          v-if="selectable"
          type="button"
          class="jb-select"
          :class="{ 'jb-select--on': selected }"
          role="checkbox"
          :aria-checked="String(selected)"
          :aria-label="selected ? `Deselect ${project.name}` : `Select ${project.name} to launch`"
          :data-testid="`jb-select-${project.id}`"
          @click="$emit('toggle-select', project)"
        >
          <v-icon size="16">{{ selected ? 'mdi-checkbox-marked' : 'mdi-checkbox-blank-outline' }}</v-icon>
        </button>
        <span class="jb-tax-pill" data-testid="jb-tax-pill">{{ project.taxonomy_alias }}</span>
        <v-tooltip location="bottom" open-delay="150">
          <template #activator="{ props: tooltipProps }">
            <h2 v-bind="tooltipProps" class="jb-title" data-testid="jb-title">
              {{ project.name }}
            </h2>
          </template>
          <div data-testid="jb-title-tooltip">
            <strong>Project UUID</strong><br />
            <span class="jb-tip-k">{{ project.id }}</span>
          </div>
        </v-tooltip>
        <span
          class="jb-status-pill"
          data-testid="jb-status-pill"
          :style="{ backgroundColor: hexToRgba(edgeColor, 0.15), color: edgeColor }"
        >
          {{ sectionLabel }}
        </span>
      </div>

      <p class="jb-meta" data-testid="jb-meta">{{ metaLine }}</p>

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

      <div class="jb-stats">
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

      <div class="jb-agents" data-testid="jb-agents-list">
        <JobsBoardAgentRow v-for="agent in agents" :key="agent.agent_id || agent.job_id || agent.id" :agent="agent" :now="now" />
      </div>

      <div class="jb-foot">
        <v-btn
          v-if="sectionLabel === JOBS_SECTION_LABELS.STAGED"
          class="jb-btn jb-btn-primary"
          size="small"
          variant="flat"
          :to="{ name: 'ProjectLaunch', params: { projectId: project.id }, query: { via: 'jobs' } }"
          data-testid="jb-btn-open"
        >
          Open
        </v-btn>
        <v-btn
          v-else
          class="jb-btn jb-btn-ghost"
          size="small"
          variant="text"
          :to="{ name: 'ProjectLaunch', params: { projectId: project.id }, query: { via: 'jobs' } }"
          data-testid="jb-btn-open"
        >
          Open
        </v-btn>

        <v-btn
          v-if="sectionLabel === JOBS_SECTION_LABELS.REVIEW"
          class="jb-btn jb-btn-review"
          size="small"
          variant="flat"
          :to="{ name: 'ProjectLaunch', params: { projectId: project.id }, query: { via: 'jobs', review: '1' } }"
          data-testid="jb-btn-review"
        >
          Review &amp; close
        </v-btn>

        <v-btn
          class="jb-btn jb-btn-ghost"
          size="small"
          variant="text"
          data-testid="jb-btn-detail"
          @click="emit('open-detail', project)"
        >
          Jobs detail
        </v-btn>

        <span class="jb-foot-spacer" />
        <v-btn
          class="jb-icon-btn"
          size="small"
          variant="text"
          icon
          title="Go to this project's Hub thread"
          data-testid="jb-btn-hub"
          @click="emit('open-hub', project)"
        >
          <v-icon size="18">mdi-forum</v-icon>
        </v-btn>
      </div>
    </v-card-text>
  </v-card>
</template>

<script setup>
import { computed } from 'vue'
import { hexToRgba } from '@/utils/colorUtils'
import { jobsSectionLabelFor, JOBS_SECTION_LABELS } from '@/utils/jobsSectionLabel'
import { jobsBoardLifecycleColor } from '@/utils/jobsBoardLifecycle'
import { aggregateSteps, aggregateWaiting, projectDurationSeconds, jobsBoardMetaLine } from '@/utils/jobsBoardCardStats'
import { formatDurationSeconds } from '@/utils/durationFormat'
import JobsBoardAgentRow from '@/components/projects/JobsBoardAgentRow.vue'

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
  selectable: {
    type: Boolean,
    default: false,
  },
  selected: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['open-detail', 'open-hub', 'toggle-select'])

const sectionLabel = computed(() => jobsSectionLabelFor(props.project, props.agents))
const edgeColor = computed(() => jobsBoardLifecycleColor(sectionLabel.value))
const showGateNote = computed(
  () => sectionLabel.value === JOBS_SECTION_LABELS.STAGED && props.headlessAllowed === false,
)
const steps = computed(() => aggregateSteps(props.agents))
const waiting = computed(() => aggregateWaiting(props.agents))
const durationLabel = computed(() => formatDurationSeconds(projectDurationSeconds(props.project, props.now)))
const metaLine = computed(() => jobsBoardMetaLine(props.project, sectionLabel.value, props.now))
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

/* FE-9555: the selection tick, sized to sit in the head row without displacing
   the taxonomy pill. Deliberately quiet until it is on -- an unselected board
   should read as a status board, not as a form. */
.jb-select {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  margin-right: 0.375rem;
  color: var(--color-text-secondary);
  background: none;
  border: none;
  cursor: pointer;
}

.jb-select:hover,
.jb-select--on {
  color: var(--color-agent-implementer);
}

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

.jb-tax-pill {
  flex: none;
  font-size: 0.67rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  padding: 3px $spacing-snug;
  border-radius: $border-radius-pill;
  background: rgba($color-accent-success, 0.15);
  color: $color-accent-success;
  font-family: $typography-font-mono;
}

.jb-title {
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

.jb-status-pill {
  flex: none;
  margin-left: auto;
  font-size: 0.67rem;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: $border-radius-pill;
  white-space: nowrap;
}

.jb-meta {
  color: $color-text-secondary;
  font-size: 0.71rem;
  margin: 0 0 12px;
  font-family: $typography-font-mono;
}

.jb-gate-note {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin: 0 0 12px;
  padding: $spacing-snug 11px;
  border-radius: $border-radius-default;
  background: rgba($color-status-blocked, 0.09);
  border: 1px solid rgba($color-status-blocked, 0.32);
  font-size: 0.72rem;
  line-height: 1.45;

  .jb-gate-icon {
    flex: none;
    color: $color-status-blocked;
    margin-top: 1px;
  }

  strong {
    display: block;
    color: $color-status-blocked;
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
  margin-bottom: 11px;
  border-top: 1px solid $color-border-tertiary;
  border-bottom: 1px solid $color-border-tertiary;
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

.jb-agents {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin-bottom: 13px;
}

.jb-foot {
  display: flex;
  align-items: center;
  gap: 7px;
}

.jb-btn {
  font-size: 0.76rem;
  font-weight: 600;
  text-transform: none;
  letter-spacing: 0;
}

.jb-btn-primary {
  background: $color-brand-yellow;
  color: $color-on-yellow-ink;
}

.jb-btn-review {
  background: $color-accent-success;
  color: $color-on-yellow-ink;
}

.jb-btn-ghost {
  color: $color-text-tertiary;
}

.jb-foot-spacer {
  margin-left: auto;
}

.jb-icon-btn {
  min-width: 36px;
}

.jb-tip-k {
  color: $color-text-secondary;
  font-family: $typography-font-mono;
}

@media (max-width: $breakpoint-mobile) {
  .jb-card-body {
    padding: 14px 14px 12px !important;
  }
}
</style>
