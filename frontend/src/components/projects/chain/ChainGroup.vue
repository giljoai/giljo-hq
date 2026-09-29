<template>
  <section
    v-if="chainCtx"
    class="cg smooth-border"
    :class="{ 'cg--highlight': highlighted }"
    :data-run-id="chainCtx.runId"
    data-testid="chain-group"
  >
    <ChainGroupHeader :chain-ctx="chainCtx" :controls="controls" :agent-count="agentCount" />

    <div class="cg-members">
      <div
        v-for="member in members"
        :key="member.tab.projectId"
        class="cg-member"
        :class="member.state === 'current' ? 'cg-member--current' : 'cg-member--quiet'"
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
          <button
            v-if="member.tab.needsReview"
            type="button"
            class="cg-review"
            :data-testid="`chain-member-review-${member.tab.projectId}`"
            @click="handleTabReview(member.tab)"
          >
            Review
          </button>
          <span v-else-if="member.tab.isCompleted" class="cg-reviewed">Reviewed</span>
          <span class="cg-spacer" />
          <v-btn
            v-if="chainCtx.locked"
            icon
            size="x-small"
            variant="text"
            class="cg-fallback"
            :title="`${REPLAY_LABEL} (${member.label} only)`"
            :aria-label="`${REPLAY_LABEL} (${member.label} only)`"
            :data-testid="`chain-member-fallback-${member.tab.projectId}`"
            @click="controls.copyMemberFallbackPrompt(member.tab.projectId)"
          >
            <v-icon size="16">mdi-recycle</v-icon>
          </v-btn>
        </div>
        <JobsBoardCard
          v-if="member.project"
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
          @review="(p) => emit('review', p)"
        />
      </div>
    </div>

    <CloseoutModal
      v-if="chainReviewTab"
      :show="showChainReview"
      :project-id="chainReviewTab.projectId"
      :project-name="chainReviewTab.name"
      :product-id="chainReviewTab.productId"
      :project-status="chainReviewTab.status || 'active'"
      suppress-navigation
      @close="showChainReview = false"
      @closeout="handleChainReviewComplete"
    />
  </section>
</template>

<script setup>
import { computed, reactive } from 'vue'
import { REPLAY_LABEL } from '@/composables/usePlayButton'
import { useChainContext } from '@/composables/useChainContext'
import { useChainGroupControls } from '@/composables/useChainGroupControls'
import { useChainMemberReview } from '@/composables/useChainMemberReview'
import CloseoutModal from '@/components/orchestration/CloseoutModal.vue'
import JobsBoardCard from '@/components/projects/JobsBoardCard.vue'
import ChainGroupHeader from './ChainGroupHeader.vue'

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
  'review',
])

const { chainCtx } = useChainContext({ runId: () => props.runId })
const controls = reactive(useChainGroupControls({ chainCtx }))
const { showChainReview, chainReviewTab, handleTabReview, handleChainReviewComplete } = useChainMemberReview({ chainCtx })

function memberState(tab) {
  if (tab.isCompleted) return 'done'
  return tab.isCurrent ? 'current' : 'waiting'
}

function memberStateLabel(member) {
  if (member.state === 'current') return 'current'
  if (member.state === 'done') return 'done'
  const step = member.tab.order + 1
  return step > 1 ? `waiting for step ${step - 1}` : 'waiting'
}

const members = computed(() =>
  (chainCtx.value?.tabs || []).map((tab) => ({
    tab,
    state: memberState(tab),
    label: tab.taxonomyAlias || tab.name || `step ${tab.order + 1}`,
    project: chainCtx.value.projects.find((p) => p.id === tab.projectId) || null,
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

.cg-review {
  background: rgba($color-brand-yellow, 0.14);
  color: $color-brand-yellow;
  border: 0;
  border-radius: $border-radius-pill;
  padding: 2px 10px;
  font: inherit;
  font-size: 0.75rem;
  font-weight: 600;
  cursor: pointer;
}

.cg-reviewed {
  font-size: 0.75rem;
  color: $color-text-secondary;
}

.cg-spacer {
  flex: 1;
}

.cg-fallback {
  color: $color-text-secondary;
}
</style>
