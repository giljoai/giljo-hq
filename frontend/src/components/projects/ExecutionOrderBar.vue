<template>
  <div class="execution-order-section" data-testid="execution-order">
    <div class="execution-order-title">Proposed Execution Order:</div>
    <div class="execution-order-phases">
      <template v-for="(phase, idx) in phases" :key="idx">
        <span v-if="idx > 0" class="phase-dot">&middot;</span>
        <div class="phase-entry">
          <span class="phase-label">{{ phase.label }}</span>
          <span class="phase-agents">
            <template v-for="(agent, aidx) in phase.agents" :key="aidx">
              <span v-if="aidx > 0" class="phase-separator">+</span>
              <span
                class="agent-tinted-badge"
                :style="{ backgroundColor: agent.tintedBg, color: agent.color }"
              >{{ agent.displayName }}</span>
            </template>
          </span>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>

defineProps({
  phases: {
    type: Array,
    required: true,
  },
})
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

.execution-order-section {
  padding: 10px 14px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  text-align: center;

  .execution-order-title {
    font-size: 0.72rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: $color-text-secondary;
    margin-bottom: 8px;
  }

  .execution-order-phases {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    align-items: center;
    gap: 6px 8px;

    .phase-dot {
      font-size: 20px;
      font-weight: 700;
      color: rgba(255, 255, 255, 0.4);
      line-height: 1;
    }

    .phase-entry {
      display: flex;
      align-items: center;
      gap: 5px;

      .phase-label {
        font-size: 0.72rem;
        font-weight: 700;
        color: white;
      }

      .phase-agents {
        display: inline-flex;
        align-items: center;
        gap: 4px;

        .agent-tinted-badge {
          white-space: nowrap;
        }

        .phase-separator {
          font-size: 14px;
          font-weight: 700;
          color: white;
        }
      }
    }
  }
}
</style>
