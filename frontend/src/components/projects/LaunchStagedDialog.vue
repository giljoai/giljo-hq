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
import { ref, computed, watch } from 'vue'
import { api } from '@/services/api'
import { useClipboard } from '@/composables/useClipboard'
import BaseDialog from '@/components/common/BaseDialog.vue'

const props = defineProps({
  modelValue: { type: Boolean, required: true },
  projects: { type: Array, required: true },
})

defineEmits(['update:modelValue'])

const MODE_OPTIONS = [
  { value: 'multi_terminal', label: 'Terminals — a separate terminal per agent, and you watch the fleet' },
  { value: 'subagent', label: 'Subagents — one session drives the worker agents itself' },
]

const { copied, copy } = useClipboard()

const executionMode = ref(null)
const prompt = ref('')
const error = ref('')
const loading = ref(false)
const serverProjects = ref([])

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
    console.error('[LaunchStagedDialog] master prompt build failed', err)
    error.value =
      err?.response?.data?.detail ||
      'Could not build the master prompt. Check the selection and try again.'
  } finally {
    loading.value = false
  }
}

watch(executionMode, buildPrompt)

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
