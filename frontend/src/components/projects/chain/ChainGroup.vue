<template>
  <section
    v-if="chainCtx"
    class="cg smooth-border"
    :class="{ 'cg--highlight': highlighted }"
    :data-run-id="chainCtx.runId"
    data-testid="chain-group"
  >
    <ChainGroupHeader :chain-ctx="chainCtx" :controls="controls">
      <template #controls>
        <ChainStagingActions :chain-ctx="chainCtx" :controls="controls" :agent-count="agentCount" />
      </template>
    </ChainGroupHeader>

    <div class="cg-members">
      <div
        v-for="member in members"
        :key="member.tab.projectId"
        class="cg-member"
        :class="memberClass(member)"
        :data-project-id="member.tab.projectId"
        :data-member-state="member.state"
        data-testid="chain-group-member"
      >
        <div class="cg-member-top">
          <span class="cg-step" data-testid="chain-member-step">Step {{ member.tab.order + 1 }}</span>
          <span
            class="cg-step cg-step-state"
            :class="{ 'cg-step-state--current': member.state === 'current' }"
            data-testid="chain-member-state"
          >
            &middot; {{ memberStateLabel(member) }}
          </span>
          <span v-if="!member.tab.needsReview && member.tab.isCompleted" class="cg-reviewed">Reviewed</span>
          <span class="cg-spacer" />
          <button
            v-if="canDrop(member)"
            type="button"
            class="cg-drop"
            :title="dropTooltip"
            :aria-label="`Drop ${member.label} from the chain`"
            :disabled="Boolean(controls.manageDroppingId)"
            :data-testid="`chain-member-drop-${member.tab.projectId}`"
            @click="controls.requestDrop(member.tab.projectId)"
          >
            <v-icon size="16" aria-hidden="true">mdi-close</v-icon>
          </button>
          <span v-if="memberStatusLine(member)" class="cg-member-status" data-testid="chain-member-status">
            {{ memberStatusLine(member) }}
          </span>
          <v-menu v-if="chainCtx.locked && member.state !== 'dropped'" location="bottom end">
            <template #activator="{ props: menuProps }">
              <v-btn
                v-bind="menuProps"
                icon
                size="x-small"
                variant="text"
                class="cg-more"
                :aria-label="`More actions for ${member.label}`"
                :title="`More actions for ${member.label}`"
                :data-testid="`chain-member-menu-${member.tab.projectId}`"
              >
                <v-icon size="16">mdi-dots-vertical</v-icon>
              </v-btn>
            </template>
            <v-list density="compact">
              <v-list-item
                :data-testid="`chain-member-fallback-${member.tab.projectId}`"
                @click="controls.copyMemberFallbackPrompt(member.tab.projectId)"
              >
                Run this project alone (recovery)
              </v-list-item>
            </v-list>
          </v-menu>
        </div>
        <div v-if="member.state === 'dropped'" class="cg-dropped smooth-border" data-testid="chain-member-dropped">
          <span v-if="member.tab.taxonomyAlias" class="cg-dropped-alias">{{ member.tab.taxonomyAlias }}</span>
          <span class="cg-dropped-title" :title="member.tab.name" data-testid="chain-member-dropped-title">
            {{ member.tab.name }}
          </span>
          <span class="cg-dropped-label">Dropped from chain</span>
        </div>
        <JobsBoardCard
          v-else-if="member.project"
          :project="member.project"
          :agents="agentsByProject[member.tab.projectId] || []"
          :now="now"
          :headless-allowed="headlessAllowed"
          :density="density"
          :show-staging="false"
          :chain-ctx="chainCtx"
          @open-detail="(p) => emit('open-detail', p)"
          @open-hub="(p) => emit('open-hub', p)"
          @changed="(p) => emit('changed', p)"
          @agent-messages="(a, p) => emit('agent-messages', a, p)"
          @agent-role="(a) => emit('agent-role', a)"
          @agent-job="(a) => emit('agent-job', a)"
          @edit-description="(p) => emit('edit-description', p)"
          @agent-mission-edit="(a) => emit('agent-mission-edit', a)"
          @steps="(a) => emit('steps', a)"
          @review="handleTabReview(member.tab)"
        />
        <p
          v-else-if="chainCtx.missingIds.includes(member.tab.projectId)"
          class="text-body-small"
          data-testid="chain-member-load-error"
        >
          <v-icon size="16" color="error" class="mr-1">mdi-alert-circle</v-icon>
          This step's project could not be loaded. Refresh the board to try again.
        </p>
      </div>
    </div>

    <v-alert
      v-if="controls.manageError"
      type="error"
      variant="tonal"
      density="compact"
      class="mt-3"
      data-testid="chain-drop-error"
    >
      {{ controls.manageError }}
    </v-alert>

    <BaseDialog
      :model-value="Boolean(controls.managePendingId)"
      type="danger"
      :title="controls.managePendingCancelsChain ? 'Cancel this chain?' : 'Drop the current project?'"
      :confirm-label="controls.managePendingCancelsChain ? 'Drop and cancel chain' : 'Drop from chain'"
      size="sm"
      :loading="Boolean(controls.manageDroppingId)"
      @confirm="controls.confirmDrop"
      @cancel="controls.cancelDrop"
      @update:model-value="(open) => !open && controls.cancelDrop()"
    >
      <p v-if="controls.managePendingCancelsChain">
        Dropping this project leaves one project, and one project is not a chain. The chain will be cancelled.
      </p>
      <p v-else>
        This project is running now. Dropping it parks the project and clears its plan and agents.
        The rest of the chain keeps running.
      </p>
    </BaseDialog>

    <CloseoutModal
      v-if="chainReviewTab"
      :show="showChainReview"
      :project-id="chainReviewTab.projectId"
      :project-name="chainReviewTab.name"
      :product-id="chainReviewTab.productId"
      :project-status="chainReviewTab.status || 'active'"
      suppress-navigation
      chain-review
      @close="showChainReview = false"
      @closeout="handleChainReviewComplete"
    />
  </section>
</template>

<script setup>
import { computed, reactive } from 'vue'
import { useChainContext } from '@/composables/useChainContext'
import { useChainGroupControls } from '@/composables/useChainGroupControls'
import { withChainReview } from '@/utils/jobsSectionLabel'
import { useChainMemberReview } from '@/composables/useChainMemberReview'
import BaseDialog from '@/components/common/BaseDialog.vue'
import CloseoutModal from '@/components/orchestration/CloseoutModal.vue'
import JobsBoardCard from '@/components/projects/JobsBoardCard.vue'
import ChainGroupHeader from './ChainGroupHeader.vue'
import ChainStagingActions from './ChainStagingActions.vue'

const props = defineProps({
  runId: { type: String, required: true },
  agentsByProject: { type: Object, default: () => ({}) },
  now: { type: Number, required: true },
  headlessAllowed: { type: Boolean, default: null },
  density: { type: String, default: 'detailed' },
  highlighted: { type: Boolean, default: false },
})

const emit = defineEmits([
  'open-detail',
  'open-hub',
  'changed',
  'agent-messages',
  'agent-role',
  'agent-job',
  'edit-description',
  'agent-mission-edit',
  'steps',
])

const { chainCtx } = useChainContext({ runId: () => props.runId })
const controls = reactive(useChainGroupControls({ chainCtx, agentsByProject: () => props.agentsByProject }))
const { showChainReview, chainReviewTab, handleTabReview, handleChainReviewComplete } = useChainMemberReview({ chainCtx })

function memberState(tab) {
  if (tab.isDetached) return 'dropped'
  if (tab.isCompleted) return 'done'
  return tab.isCurrent ? 'current' : 'waiting'
}

function memberStateLabel(member) {
  if (member.state === 'current') return 'current'
  if (member.state === 'done') return 'done'
  if (member.state === 'dropped') return 'dropped'
  const step = member.tab.order + 1
  return step > 1 ? `waiting for step ${step - 1}` : 'waiting'
}

function memberClass(member) {
  if (member.state === 'dropped') return ['cg-member--quiet', 'cg-member--dropped']
  return member.state === 'current' ? 'cg-member--current' : 'cg-member--quiet'
}

function canDrop(member) {
  return controls.manageRows?.some((r) => r.projectId === member.tab.projectId && r.kind === 'droppable') || false
}
const dropTooltip = computed(() =>
  controls.managePhase === 'started'
    ? 'Drop this project from the chain. It is parked, not deleted.'
    : 'Drop this project from the chain.',
)

function memberStatusLine(member) {
  if (member.state === 'done' || member.state === 'dropped') return ''
  if (member.state === 'current') return 'Run by the conductor'
  return `Starts after step ${member.tab.order} is merged`
}

function memberProject(tab) {
  const project = chainCtx.value.projects.find((p) => p.id === tab.projectId)
  return project ? withChainReview(project, tab.needsReview) : null
}

const members = computed(() =>
  (chainCtx.value?.tabs || []).map((tab) => ({
    tab,
    state: memberState(tab),
    label: tab.name || tab.taxonomyAlias || `step ${tab.order + 1}`,
    project: memberProject(tab),
  })),
)

const agentCount = computed(() =>
  (chainCtx.value?.tabs || []).reduce((sum, tab) => sum + (props.agentsByProject[tab.projectId]?.length || 0), 0),
)
</script>

<style scoped lang="scss">
@use '@/styles/design-tokens' as *;

.cg {
  --smooth-border-color: #{rgba($color-brand-yellow, 0.35)};
  background: $color-container-background;
  border-radius: $border-radius-rounded;
  padding: 20px;
  margin-bottom: 24px;
  min-width: 0;

  &--highlight {
    --smooth-border-color: #{$color-brand-yellow};
    box-shadow: 0 0 0 2px rgba($color-brand-yellow, 0.35);
  }
}

.cg-members {
  display: grid;
  gap: 16px;
  // FE-9682: the column floor never exceeds the frame, so a member never
  // overflows it; side by side when there is room, stacked when narrow.
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 420px), 1fr));
  margin-top: 16px;
  min-width: 0;
}

// FE-9682: no desaturation. Every member keeps its colour; the current one
// wears the brand ring and the others a blue-grey ring of the same weight (FE-9686).
.cg-member {
  min-width: 0;
  display: flex;
  flex-direction: column;
  border-radius: $border-radius-rounded;
  // FE-9665: padding gives the current member's ring room to sit AROUND its
  // content instead of flush against it.
  padding: 8px;

  &--current {
    // inset (not an outward ring) matches the smooth-border technique used
    // everywhere else in this file (.cg) so the ring reads as a border, not
    // an offset halo.
    box-shadow: inset 0 0 0 2px rgba($color-brand-yellow, 0.55);
  }

  &--quiet {
    box-shadow: inset 0 0 0 2px rgba($color-text-hover, 0.55);
  }
}

.cg-member-top {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
  min-height: 28px;
}

.cg-step {
  font-family: $typography-font-mono;
  font-size: 0.7rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: $color-text-secondary;
}

.cg-step-state {
  font-weight: 500;

  &--current {
    color: $color-brand-yellow;
  }
}

.cg-reviewed {
  font-size: 0.75rem;
  color: $color-text-secondary;
}

.cg-spacer {
  flex: 1;
}

.cg-member-status {
  font-size: 0.72rem;
  color: $color-text-secondary;
}

.cg-drop {
  background: none;
  border: 0;
  padding: 2px;
  line-height: 1;
  border-radius: 6px;
  color: $color-status-error;
  cursor: pointer;

  &:hover:not(:disabled),
  &:focus-visible {
    background: rgba($color-status-error, 0.15);
  }

  &:focus-visible {
    outline: 2px solid $color-status-error;
    outline-offset: 1px;
  }

  &:disabled {
    cursor: default;
    opacity: 0.6;
  }
}

.cg-member--dropped {
  box-shadow: inset 0 0 0 2px rgba($color-text-hover, 0.25);
}

.cg-dropped {
  --smooth-border-color: var(--border-subtle);
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 14px 16px;
  border-radius: $border-radius-rounded;
}

.cg-dropped-alias {
  font-family: $typography-font-mono;
  font-size: 0.7rem;
  color: $color-text-secondary;
  opacity: 0.7;
}

.cg-dropped-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: $color-text-secondary;
  opacity: 0.7;
}

.cg-dropped-label {
  font-size: 0.75rem;
  color: $color-brand-yellow;
}

.cg-more {
  color: $color-text-secondary;
}
</style>
