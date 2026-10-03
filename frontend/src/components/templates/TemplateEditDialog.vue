<template>
  <v-dialog :model-value="modelValue" max-width="900px" persistent retain-focus scrollable @update:model-value="$emit('update:modelValue', $event)">
    <v-card v-draggable class="smooth-border">
      <div class="dlg-header">
        <span class="dlg-title">{{ template.id ? 'Edit Template' : 'Create new Template' }}</span>
        <v-btn icon variant="text" class="dlg-close" aria-label="Close" @click="$emit('close')">
          <v-icon>mdi-close</v-icon>
        </v-btn>
      </div>

      <v-card-text>
        <v-container>
          <v-row>
            <v-col cols="6">
              <v-select
                :model-value="template.role"
                :items="roleOptions"
                data-testid="role-select"
                label="Role"
                :rules="[(v) => !!v || 'Role is required']"
                variant="outlined"
                density="compact"
                aria-label="Select agent role"
                @update:model-value="$emit('role-change', $event)"
              >
                <template #append-inner>
                  <v-tooltip location="top">
                    <template #activator="{ props }">
                      <v-icon v-bind="props" size="small" color="primary">mdi-help-circle</v-icon>
                    </template>
                    <span>Required field - Select the agent role</span>
                  </v-tooltip>
                </template>
              </v-select>
            </v-col>

            <v-col cols="6">
              <v-text-field
                :model-value="template.custom_suffix"
                label="Custom Suffix (optional)"
                density="compact"
                aria-label="Custom agent name suffix"
                @update:model-value="update('custom_suffix', $event)"
              >
                <template #append-inner>
                  <v-tooltip location="top">
                    <template #activator="{ props }">
                      <v-icon v-bind="props" size="small" color="primary">mdi-help-circle</v-icon>
                    </template>
                    <span>Add a suffix to customize the agent name (e.g., 'implementer-fastapi')</span>
                  </v-tooltip>
                </template>
              </v-text-field>
              <div v-if="generatedName" class="text-body-small text-primary mt-n2">
                Agent Name: <strong>{{ generatedName }}</strong>
              </div>
            </v-col>

            <v-col cols="6">
              <v-text-field
                :model-value="template.cli_tool ?? ''"
                label="Harness"
                placeholder="default"
                variant="outlined"
                density="compact"
                maxlength="20"
                :rules="[harnessNameRule]"
                hint="Blank or 'default' = the orchestrator's own harness, or a name such as claude or codex"
                persistent-hint
                data-testid="cli-tool-input"
                aria-label="Harness this agent runs in"
                @update:model-value="update('cli_tool', $event)"
              />
            </v-col>

            <v-col cols="6">
              <v-text-field
                :model-value="template.model ?? 'inherit'"
                label="Model"
                variant="outlined"
                density="compact"
                maxlength="120"
                hint="Prose instruction for the harness; 'inherit' = same as the orchestrator"
                persistent-hint
                data-testid="model-input"
                aria-label="Preferred model for this agent"
                @update:model-value="update('model', $event)"
              />
            </v-col>
            <v-col cols="6">
              <v-text-field
                :model-value="template.effort ?? 'inherit'"
                label="Effort"
                variant="outlined"
                density="compact"
                maxlength="120"
                hint="Prose instruction for the harness; 'inherit' = same as the orchestrator"
                persistent-hint
                data-testid="effort-input"
                aria-label="Preferred effort level for this agent"
                @update:model-value="update('effort', $event)"
              />
            </v-col>


            <v-col cols="12">
              <v-text-field
                :model-value="template.description"
                label="Description"
                density="compact"
                hint="Short description of agent responsibilities (used by all platforms)"
                persistent-hint
                aria-label="Agent description"
                @update:model-value="update('description', $event)"
              >
                <template #append-inner>
                  <v-tooltip location="top">
                    <template #activator="{ props }">
                      <v-icon v-bind="props" size="small" color="primary">mdi-help-circle</v-icon>
                    </template>
                    <span>Brief description of what this agent does</span>
                  </v-tooltip>
                </template>
              </v-text-field>
            </v-col>

            <v-col cols="12">
              <div class="d-flex align-center mb-2">
                <span class="text-title-small">Role & Expertise</span>
                <v-tooltip location="top">
                  <template #activator="{ props }">
                    <v-icon v-bind="props" size="small" color="primary" class="ml-2"
                      >mdi-help-circle</v-icon
                    >
                  </template>
                  <span
                    >Describe this agent's specialization, expertise, and personality.
                    This content defines who the agent is.</span
                  >
                </v-tooltip>
              </div>
              <v-textarea
                :model-value="template.user_instructions"
                label="Role & Expertise"
                hint="Describe this agent's specialization, expertise, and personality."
                persistent-hint
                rows="12"
                variant="outlined"
                density="compact"
                class="template-editor"
                aria-label="Agent role and expertise"
                @update:model-value="update('user_instructions', $event)"
              />
            </v-col>

          </v-row>
        </v-container>
      </v-card-text>

      <div class="dlg-footer">
        <v-spacer />
        <v-btn variant="text" @click="$emit('close')">Cancel</v-btn>
        <v-btn
          color="primary"
          variant="flat"
          :loading="saving"
          :disabled="!hasChanges"
          @click="$emit('save')"
        >
          Save
        </v-btn>
      </div>
    </v-card>
  </v-dialog>
</template>

<script setup>

const props = defineProps({
  modelValue: {
    type: Boolean,
    default: false,
  },
  template: {
    type: Object,
    default: () => ({}),
  },
  saving: {
    type: Boolean,
    default: false,
  },
  generatedName: {
    type: String,
    default: '',
  },
  roleOptions: {
    type: Array,
    default: () => [],
  },
  hasChanges: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits([
  'update:modelValue',
  'update:template',
  'save',
  'close',
  'role-change',
])

const HARNESS_NAME_PATTERN = /^[A-Za-z0-9._-]*$/
function harnessNameRule(value) {
  return HARNESS_NAME_PATTERN.test((value || '').trim()) || 'Use letters, digits, dash, underscore or dot'
}

function update(field, value) {
  const next = { ...props.template, [field]: value }
  emit('update:template', next)
}
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

.template-editor {
  font-family: 'Roboto Mono', monospace;
  background: var(--v-theme-background);

  :deep(.v-field__input) {
    color: var(--v-theme-on-surface);
  }
}
</style>
