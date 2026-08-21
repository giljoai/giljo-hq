<template>
  <v-dialog :model-value="modelValue" max-width="900px" persistent retain-focus scrollable @update:model-value="$emit('update:modelValue', $event)">
    <v-card v-draggable class="smooth-border">
      <div class="dlg-header">
        <span class="dlg-title">{{ template.id ? 'Edit' : 'Create' }} Template</span>
        <v-btn icon variant="text" class="dlg-close" aria-label="Close" @click="$emit('close')">
          <v-icon>mdi-close</v-icon>
        </v-btn>
      </div>

      <v-card-text>
        <v-container>
          <v-row>
            <!-- Role / Suffix — single row -->
            <v-col cols="6">
              <v-select
                :model-value="template.role"
                :items="roleOptions"
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

            <!-- Coding tool (INF-6049c: per-role CLI tool mapping) -->
            <v-col cols="6">
              <v-select
                :model-value="template.cli_tool || 'claude'"
                :items="codingToolOptions"
                label="Coding tool"
                variant="outlined"
                density="compact"
                data-testid="cli-tool-select"
                aria-label="Select coding CLI tool for this agent"
                @update:model-value="update('cli_tool', $event)"
              >
                <template #append-inner>
                  <v-tooltip location="top">
                    <template #activator="{ props }">
                      <v-icon v-bind="props" size="small" color="primary">mdi-help-circle</v-icon>
                    </template>
                    <span
                      >Which CLI this agent launches in for multi-terminal runs. Each agent's
                      terminal is pre-seeded for its assigned tool. Defaults to Claude.</span
                    >
                  </v-tooltip>
                </template>
              </v-select>
            </v-col>

            <!-- BE-9394: the tenant-wide RETIRE switch, and the only writer for it.
                 Deliberately distinct from the Active switch in the agents list, which
                 writes just this product's junction row (useProductAgentAssignments).
                 Two controls, two meanings: that one is "active in the product I am
                 working in", this one is "available at all, anywhere". Edit-only --
                 a new agent is created available (BE-9391), so offering the choice on
                 create would imply a decision nothing acts on. -->
            <!-- FE-9385c: the heading is gone and the control is one line. The
                 switch plus its own label already said what the heading said, and
                 the label no longer rewrites itself when you toggle it -- a caption
                 that changes as you flip the switch is harder to read at a glance,
                 not easier, and the switch position already carries the state. -->
            <v-col v-if="template.id" cols="6">
              <div class="d-flex align-center">
                <v-switch
                  :model-value="!!template.is_active"
                  label="Available in all products"
                  color="primary"
                  density="compact"
                  hide-details
                  inset
                  data-testid="retire-switch"
                  aria-label="Available in all products"
                  @update:model-value="update('is_active', $event)"
                />
                <v-tooltip location="top" max-width="340">
                  <template #activator="{ props }">
                    <v-icon v-bind="props" size="small" color="primary" class="ml-2"
                      >mdi-help-circle</v-icon
                    >
                  </template>
                  <span
                    >Covers every product. Turn it off to stop offering this agent
                    anywhere. The <strong>Active here</strong> switch in the agents list
                    is separate — it only affects the product you are working in.</span
                  >
                </v-tooltip>
              </div>
            </v-col>

            <!-- Description -->
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

            <!-- Role & Expertise Editor (Handover 0814: replaces System Prompt) -->
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
/**
 * TemplateEditDialog.vue — FE-6042b
 *
 * Presentational dialog for creating/editing an agent template.
 * No API calls. No composables. All state flows in via props/model,
 * all interactions out via emits.
 *
 * Container (TemplateManager) retains: useTemplateData, editingTemplate ref,
 * generatedName, resetEditingTemplate, saveTemplate, onRoleChange.
 *
 * Edition scope: CE
 */

/**
 * @type {boolean} modelValue - Whether the dialog is open (v-model)
 * @type {Object}  template   - The editing template object
 * @type {boolean} saving     - Whether save is in progress
 * @type {string}  generatedName - Auto-generated agent name preview
 * @type {Array}   roleOptions   - Available role choices for the select
 * @type {boolean} hasChanges    - Whether the form has unsaved changes
 */
const props = defineProps({
  /** Whether the dialog is open */
  modelValue: {
    type: Boolean,
    default: false,
  },
  /** The template being created or edited */
  template: {
    type: Object,
    default: () => ({}),
  },
  /** Whether a save operation is in progress */
  saving: {
    type: Boolean,
    default: false,
  },
  /** Auto-generated agent name from role + suffix */
  generatedName: {
    type: String,
    default: '',
  },
  /** Available roles for the select dropdown */
  roleOptions: {
    type: Array,
    default: () => [],
  },
  /** Whether the form has unsaved changes (controls Save button disabled state) */
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

// INF-6049c: the per-role coding-tool vocabulary (matches the INF-6049b mode enum
// + the backend agent_templates.cli_tool values). Default is claude when unset.
const codingToolOptions = [
  { title: 'Claude', value: 'claude' },
  { title: 'Codex', value: 'codex' },
  { title: 'Gemini', value: 'gemini' },
  { title: 'Antigravity', value: 'antigravity' },
]

/**
 * Emit a field update for the template object.
 * Container listens via @update:template and mutates editingTemplate.
 */
function update(field, value) {
  emit('update:template', { ...props.template, [field]: value })
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
