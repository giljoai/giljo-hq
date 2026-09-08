<template>
  <BaseDialog
    :model-value="modelValue"
    type="primary"
    title="Launch staged projects"
    size="lg"
    persistent
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <p class="text-body-medium text-muted-a11y mb-4">
      These missions run as one chain, in this order. Nothing starts here — you copy the prompt
      below into one terminal, and that session drives them.
    </p>

    <!-- (a) the missions being approved -->
    <ol class="lsd-missions" data-testid="launch-staged-missions">
      <li v-for="project in listedProjects" :key="project.project_id" class="lsd-mission">
        <div class="lsd-mission-head">
          <span class="lsd-alias">{{ project.taxonomy_alias }}</span>
          <span class="lsd-name">{{ project.name }}</span>
        </div>
        <p class="lsd-mission-body">
          {{ project.mission || 'No mission authored yet.' }}
        </p>
      </li>
    </ol>

    <!-- (b) the execution-mode question -->
    <div class="lsd-mode" data-testid="launch-staged-mode">
      <h3 class="text-body-large mb-1">How should this run work?</h3>
      <v-radio-group v-model="executionMode" hide-details density="compact">
        <v-radio
          v-for="option in MODE_OPTIONS"
          :key="option.value"
          :value="option.value"
          :label="option.label"
          :data-testid="`launch-staged-mode-${option.value}`"
        />
      </v-radio-group>
    </div>

    <!-- (c) the one copyable master prompt -->
    <div v-if="loading" class="lsd-prompt-state">
      <v-progress-circular indeterminate size="24" color="primary" />
      <span class="ml-2">Building the master prompt…</span>
    </div>

    <v-alert v-else-if="error" type="error" variant="tonal" data-testid="launch-staged-error">
      {{ error }}
    </v-alert>

    <div v-else-if="prompt" class="lsd-prompt">
      <pre class="lsd-prompt-body">{{ prompt }}</pre>
    </div>

    <template #actions>
      <v-btn variant="text" @click="$emit('update:modelValue', false)">Close</v-btn>
      <v-btn
        v-if="prompt && !error"
        color="primary"
        variant="flat"
        data-testid="launch-staged-copy"
        @click="onCopy"
      >
        {{ copied ? 'Copied' : 'Copy master prompt' }}
      </v-btn>
    </template>
  </BaseDialog>
</template>

<script setup>
/**
 * LaunchStagedDialog.vue — FE-9555
 *
 * The board-level "Launch staged…" confirm dialog: lists the missions being
 * approved, asks the execution-mode question, and hands over ONE copyable master
 * prompt for the session that will drive the run.
 *
 * Ruling 3 — this dialog is UI ERGONOMICS, not a server gate. The real gate is
 * server-side (the staging pause, and launch_implementation admission), and a
 * headless agent never sees this component at all. Nothing here is written as
 * though it were protecting anything: its job is to put the missions in front of
 * a human before they commit, and to ask the one question.
 *
 * Ruling 4 — the UI door NEVER executes. This dialog prepares a prompt. It does
 * not create the sequence_run, does not launch, does not stage. The pasted
 * session writes the record itself via link_projects, which is why "create the
 * run while we're here" is deliberately absent: it would put a second writer on
 * a record that has exactly one.
 *
 * BE-9504a — the prompt text is NEVER assembled here. It comes whole from the
 * server-side generator, so the UI copy and the MCP payload cannot drift apart a
 * sentence at a time.
 *
 * Edition scope: Both.
 */
import { ref, computed, watch } from 'vue'
import { api } from '@/services/api'
import { useClipboard } from '@/composables/useClipboard'
import BaseDialog from '@/components/common/BaseDialog.vue'

const props = defineProps({
  modelValue: { type: Boolean, required: true },
  /** The board rows the user selected: { id, name, taxonomy_alias }. */
  projects: { type: Array, required: true },
})

defineEmits(['update:modelValue'])

const MODE_OPTIONS = [
  { value: 'multi_terminal', label: 'Terminals — a separate terminal per agent, and you watch the fleet' },
  { value: 'subagent', label: 'Subagents — one session drives the worker agents itself' },
]

const { copied, copy } = useClipboard()

// NULL until the user chooses, matching ExecutionModeSelector's NULL-state
// design. A pre-selected radio is a silent pick wearing a question's clothes,
// and ruling 6 is that this question gets ASKED.
const executionMode = ref(null)
const prompt = ref('')
const error = ref('')
const loading = ref(false)
const serverProjects = ref([])

// Before the server has answered, list what the board already knows. The server's
// list replaces it as soon as it arrives — it carries the missions, and it is the
// list the prompt was actually built from.
const listedProjects = computed(() =>
  serverProjects.value.length
    ? serverProjects.value
    : props.projects.map((p) => ({
        project_id: p.id,
        taxonomy_alias: p.taxonomy_alias || '',
        name: p.name || '',
        mission: '',
      })),
)

async function buildPrompt() {
  if (!executionMode.value) return
  loading.value = true
  error.value = ''
  prompt.value = ''
  try {
    const response = await api.prompts.buildMasterPrompt({
      project_ids: props.projects.map((p) => p.id),
      execution_mode: executionMode.value,
    })
    prompt.value = response.data.prompt
    serverProjects.value = response.data.projects || []
  } catch (err) {
    // Surfaced, never swallowed: an empty prompt box with a live Copy button
    // hands the user an empty clipboard and a run that never starts.
    console.error('[LaunchStagedDialog] master prompt build failed', err)
    error.value =
      err?.response?.data?.detail ||
      'Could not build the master prompt. Check the selection and try again.'
  } finally {
    loading.value = false
  }
}

watch(executionMode, buildPrompt)

// Reopening with a different selection must not show the previous run's prompt.
watch(
  () => props.modelValue,
  (open) => {
    if (!open) return
    executionMode.value = null
    prompt.value = ''
    error.value = ''
    serverProjects.value = []
  },
)

async function onCopy() {
  await copy(prompt.value)
}

defineExpose({ executionMode, prompt, error, loading })
</script>

<style scoped lang="scss">
.lsd-missions {
  list-style: none;
  padding: 0;
  margin: 0 0 1.5rem;
}

.lsd-mission + .lsd-mission {
  margin-top: 0.75rem;
  border-top: 1px solid var(--color-border-subtle);
  padding-top: 0.75rem;
}

.lsd-mission-head {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
}

.lsd-alias {
  font-family: var(--font-mono, monospace);
  font-size: 0.8125rem;
  color: var(--color-agent-implementer);
}

.lsd-name {
  font-weight: 600;
}

.lsd-mission-body {
  margin: 0.25rem 0 0;
  color: var(--color-text-secondary);
}

.lsd-mode {
  margin-bottom: 1.25rem;
}

.lsd-prompt-state {
  display: flex;
  align-items: center;
}

.lsd-prompt-body {
  max-height: 18rem;
  overflow: auto;
  padding: 0.75rem;
  border-radius: 6px;
  background: var(--color-surface-sunken, rgba(0, 0, 0, 0.25));
  font-family: var(--font-mono, monospace);
  font-size: 0.8125rem;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
