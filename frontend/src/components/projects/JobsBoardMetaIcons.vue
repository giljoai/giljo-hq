<template>
  <span class="jb-ints" data-testid="jb-meta-icons">
    <v-tooltip location="bottom" max-width="300" open-delay="150">
      <template #activator="{ props: tooltipProps }">
        <button
          v-bind="tooltipProps"
          type="button"
          class="jb-int"
          :class="stateClass(gitEnabled)"
          data-testid="git-status-icon"
          aria-label="Git integration status"
          @click="goToIntegrations"
        >
          <v-icon size="14">mdi-git</v-icon>
        </button>
      </template>
      <span v-if="!integrationsResolved">Checking Git integration status.</span>
      <span v-else-if="gitEnabled">Git integration enabled.</span>
      <span v-else>Git disabled. Click to enable.</span>
    </v-tooltip>
    <v-tooltip location="bottom" max-width="300" open-delay="150">
      <template #activator="{ props: tooltipProps }">
        <button
          v-bind="tooltipProps"
          type="button"
          class="jb-int"
          :class="modeTool ? 'jb-int--on' : 'jb-int--off'"
          data-testid="agentic-tool-icon"
          :aria-label="modeTool ? modeTool.alt : 'No execution mode picked yet'"
          @click="goToIntegrations"
        >
          <v-icon size="14">{{ modeTool ? modeTool.icon : 'mdi-monitor-multiple' }}</v-icon>
        </button>
      </template>
      <span v-if="modeTool">{{ modeTool.label }} mode active.</span>
      <span v-else>No execution mode picked yet.</span>
    </v-tooltip>
  </span>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { isSubagentExecutionMode } from '@/composables/useExecutionMode'

const props = defineProps({
  gitEnabled: { type: Boolean, default: false },
  integrationsResolved: { type: Boolean, default: false },
  executionMode: { type: String, default: '' },
})

const router = useRouter()
function goToIntegrations() {
  router.push({ path: '/tools', query: { tab: 'connect' } })
}

function stateClass(on) {
  if (!props.integrationsResolved) return 'jb-int--pending'
  return on ? 'jb-int--on' : 'jb-int--off'
}

const modeTool = computed(() => {
  if (!props.executionMode) return null
  if (isSubagentExecutionMode(props.executionMode)) {
    return { icon: 'mdi-connection', label: 'Subagent', alt: 'Subagent mode active' }
  }
  return { icon: 'mdi-monitor-multiple', label: 'Multi Terminal', alt: 'Multi terminal mode active' }
})
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

.jb-ints {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  margin-left: 2px;
  padding-left: 8px;
  border-left: 1px solid $color-border-secondary;
}

.jb-int {
  display: inline-grid;
  place-items: center;
  width: 20px;
  height: 20px;
  border-radius: $border-radius-sharp;
  background: none;
  border: 0;
  padding: 0;
  cursor: pointer;
  color: $color-text-secondary;

  &:hover,
  &:focus-visible {
    background: rgba(255, 255, 255, 0.06);
  }

  &--on {
    color: $color-brand-yellow;
  }

  &--off {
    color: $color-text-muted;
    opacity: 0.45;
  }

  &--pending {
    opacity: 0.6;
  }
}
</style>
