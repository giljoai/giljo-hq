<template>
  <!-- FE-9555: "Execution mode must be ASKED, both doors." Staging
       refuses to pick for a headless caller, and the dashboard's selector stays
       unchosen until the user chooses. This is the single place to say "stop
       asking, always do X".

       Rendered as a POLICY ROW, deliberately matching OrchestrationToggles'
       .hitl-toggle-bar rows beside it (control, then muted label, then info
       tooltip) — this is the third account-wide orchestration policy on that
       surface, and it must read as one of the family, not as a form. -->
  <div class="emd-row" data-test="execution-mode-default-setting">
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
      <!-- `item.subtitle`, NOT `item.raw.subtitle`. In this Vuetify version the
           #item slot hands over the raw option object directly (same as
           ProductTestingTab and ProjectCreateEditDialog read item.icon /
           item.color). Reaching through `.raw` threw
           "Cannot read properties of undefined" for every option and the whole
           menu silently failed to open -- the caret flipped and no panel
           rendered. Invisible to the unit tests, which stub v-select. -->
      <template #item="{ props: itemProps, item }">
        <v-list-item v-bind="itemProps" :subtitle="item?.subtitle" />
      </template>
    </v-select>
    <span class="emd-label">Execution mode when staging a project</span>
    <v-tooltip location="bottom" max-width="360">
      <template #activator="{ props: tipProps }">
        <v-icon v-bind="tipProps" size="16" class="emd-info">mdi-information-outline</v-icon>
      </template>
      How work should run when you stage a project. Leave this on Ask every time and staging
      will put the question to you each time — from the dashboard or from your connected
      coding agent. Pick a mode and it stops asking and always uses that mode.
    </v-tooltip>
  </div>
</template>

<script setup>
/**
 * The account-level execution-mode default, as shown under Tools -> Agents.
 *
 * Its own component rather than more markup in ToolsView.vue, which sits on the
 * 800-line guardrail -- and because the option wording is a real decision worth
 * having one home: the subtitles repeat the sentences the headless
 * EXECUTION_MODE_REQUIRED refusal carries, so a user who was asked by their
 * coding agent and came here to stop being asked recognises the options rather
 * than re-learning them.
 *
 * Edition scope: Both.
 */
import { ref, onMounted } from 'vue'
import { EXECUTION_MODE_DEFAULT_OPTIONS } from '@/utils/executionModeDefault'
import { useSettingsStore } from '@/stores/settings'
import { useToast } from '@/composables/useToast'

// Self-contained: this control loads and saves its own value rather than taking a
// v-model and a handler from the host. Its home (the Agents tab) has no Save
// button -- TemplateManager beside it persists inline too -- so a control that
// only emitted upward would look set while having saved nothing, and the user
// would believe staging had stopped asking when it had not.
const settingsStore = useSettingsStore()
const { showToast } = useToast()

const executionModeDefault = ref(EXECUTION_MODE_DEFAULT_OPTIONS[0].value)
const saving = ref(false)

onMounted(async () => {
  // The store's loader swallows failures and answers 'ask', so a settings read
  // that fell over renders the safe choice rather than a blank select.
  executionModeDefault.value = await settingsStore.loadExecutionModeDefault()
})

async function save(choice) {
  saving.value = true
  try {
    executionModeDefault.value = await settingsStore.updateExecutionModeDefault(choice)
  } catch (error) {
    console.error('[ExecutionModeDefaultSelect] save failed', error)
    showToast({ message: 'Could not save the execution mode. Please try again.', type: 'error' })
    // Re-read rather than keep the optimistic value: the control must show what
    // the account actually holds, not what the user hoped it now holds.
    executionModeDefault.value = await settingsStore.loadExecutionModeDefault()
  } finally {
    saving.value = false
  }
}

defineExpose({ executionModeDefault, save })
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

/* Mirrors OrchestrationToggles' .hitl-toggle-bar metrics exactly (gap 8px,
   12px bottom rhythm, 4px lead-in, 0.875rem muted label) so the three policy
   rows on the Agents tab read as one block. Tokens only — no hardcoded hex. */
.emd-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  padding-left: 4px;
}

/* Trim copied from TemplateManager's .filter-select (the Role / Status boxes on
   this same tab): the light grey-blue inset hairline plus the default radius.
   Operator direction 2026-09-04 -- this control must template off those, not
   invent its own field treatment. `--smooth-border-color` is the token; the
   rgba is the same documented fallback those rules carry. */
.emd-select {
  flex: 0 0 200px;
}

.emd-select :deep(.v-field) {
  box-shadow: inset 0 0 0 1px var(--smooth-border-color, rgba(255, 255, 255, 0.1));
  border-radius: $border-radius-default;
}

.emd-label {
  font-size: 0.875rem;
  color: var(--text-muted);
}

.emd-info {
  color: var(--text-muted);
  cursor: help;
}
</style>
