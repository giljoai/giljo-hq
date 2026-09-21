<template>
  <div class="setting-row" data-test="execution-mode-default-setting">
    <div class="setting-row-text">
      <div class="setting-row-name">
        Execution mode when staging a project
        <v-tooltip location="bottom" max-width="360">
          <template #activator="{ props: tipProps }">
            <v-icon v-bind="tipProps" size="15" class="setting-row-info"
              >mdi-information-outline</v-icon
            >
          </template>
          How work should run when you stage a project. Leave this on Ask every time and staging
          will put the question to you each time — from the dashboard or from your connected
          coding agent. Pick a mode and it stops asking and always uses that mode.
        </v-tooltip>
      </div>
      <div class="setting-row-help">Ask every time, or always use one mode.</div>
    </div>
    <div class="setting-row-control">
      <v-select
        :model-value="executionModeDefault"
        :items="EXECUTION_MODE_DEFAULT_OPTIONS"
        item-title="title"
        item-value="value"
        variant="solo"
        flat
        density="compact"
        hide-details
        :loading="saving"
        aria-label="Execution mode when staging a project"
        class="emd-select"
        data-test="execution-mode-default-select"
        @update:model-value="save"
      >
        <template #item="{ props: itemProps, item }">
          <v-list-item v-bind="itemProps" :subtitle="item?.subtitle" />
        </template>
      </v-select>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { EXECUTION_MODE_DEFAULT_OPTIONS } from '@/utils/executionModeDefault'
import { useSettingsStore } from '@/stores/settings'
import { useToast } from '@/composables/useToast'

const settingsStore = useSettingsStore()
const { showToast } = useToast()

const executionModeDefault = ref(EXECUTION_MODE_DEFAULT_OPTIONS[0].value)
const saving = ref(false)

onMounted(async () => {
  executionModeDefault.value = await settingsStore.loadExecutionModeDefault()
})

async function save(choice) {
  saving.value = true
  try {
    executionModeDefault.value = await settingsStore.updateExecutionModeDefault(choice)
  } catch (error) {
    console.error('[ExecutionModeDefaultSelect] save failed', error)
    showToast({ message: 'Could not save the execution mode. Please try again.', type: 'error' })
    executionModeDefault.value = await settingsStore.loadExecutionModeDefault()
  } finally {
    saving.value = false
  }
}

defineExpose({ executionModeDefault, save })
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

/* Trim copied from TemplateManager's .filter-select (the Role / Status boxes on
   this same tab): the light grey-blue inset hairline plus the default radius.
   Operator direction 2026-09-04 -- this control must template off those, not
   invent its own field treatment. `--smooth-border-color` is the token; the
   rgba is the same documented fallback those rules carry. */
.emd-select {
  flex: 0 0 190px;
}

.emd-select :deep(.v-field) {
  box-shadow: inset 0 0 0 1px var(--smooth-border-color, rgba(255, 255, 255, 0.1));
  border-radius: $border-radius-default;
}
</style>
