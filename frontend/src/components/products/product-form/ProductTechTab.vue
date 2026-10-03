<template>
  <div data-testid="product-form-panel-tech">
    <div class="text-body-large mb-1">Technology Stack Configuration</div>
    <div class="text-body-small text-warning mb-4">
      Optionally included as context source by orchestrator.
      <v-chip size="x-small" color="success" variant="tonal" class="ml-2">Activated in Context Manager</v-chip>
    </div>

    <v-textarea
      v-for="field in FIELDS"
      :key="field.key"
      v-model="form.techStack[field.key]"
      :placeholder="field.placeholder"
      :hint="field.hint"
      persistent-hint
      variant="outlined"
      density="comfortable"
      :rows="field.rows"
      auto-grow
      class="mb-4"
    >
      <template #label>
        <span>{{ field.label }}</span>
      </template>
    </v-textarea>

    <div class="mb-4">
      <label class="text-title-small mb-2 d-block">Target Platform(s)</label>
      <div class="text-body-small text-muted-a11y mb-3">
        Select the operating systems this product is designed for
      </div>

      <div class="d-flex flex-wrap ga-3">
        <v-checkbox
          v-for="platform in PLATFORMS"
          :key="platform.value"
          v-model="form.targetPlatforms"
          :value="platform.value"
          :label="platform.label"
          hide-details
          density="comfortable"
          :disabled="isAllPlatformSelected"
          @update:model-value="$emit('platform-change')"
        />
        <v-checkbox
          v-model="form.targetPlatforms"
          value="all"
          label="All (Cross-platform)"
          hide-details
          density="comfortable"
          color="primary"
          @update:model-value="$emit('all-platform-change', $event)"
        />
      </div>

      <div v-if="platformValidationError" class="text-error text-body-small mt-2">
        {{ platformValidationError }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const FIELDS = [
  { key: 'programming_languages', label: 'Programming Languages', placeholder: 'Python 3.11, JavaScript ES2023, TypeScript 5.2', hint: 'List all programming languages used (comma-separated or line-by-line)', rows: '3' },
  { key: 'frontend_frameworks', label: 'Frontend Frameworks & Libraries', placeholder: 'Vue 3, Vuetify 3, Pinia, Vue Router', hint: 'List frontend technologies (frameworks, libraries, tools)', rows: '3' },
  { key: 'backend_frameworks', label: 'Backend Frameworks & Services', placeholder: 'FastAPI 0.104, SQLAlchemy 2.0, Alembic, asyncio', hint: 'List backend technologies (frameworks, ORMs, services)', rows: '3' },
  { key: 'databases_storage', label: 'Databases & Data Storage', placeholder: 'PostgreSQL 16, Redis 7, Vector embeddings (pgvector)', hint: 'List databases and data storage solutions', rows: '3' },
  { key: 'infrastructure', label: 'Infrastructure & DevOps', placeholder: 'Docker, Kubernetes, GitHub Actions CI/CD, AWS (EC2, S3, RDS)', hint: 'List infrastructure and deployment tools', rows: '3' },
]
const PLATFORMS = [
  { value: 'windows', label: 'Windows' },
  { value: 'linux', label: 'Linux' },
  { value: 'macos', label: 'macOS' },
  { value: 'android', label: 'Android' },
  { value: 'ios', label: 'iOS' },
  { value: 'web', label: 'Web' },
]

const props = defineProps({
  form: {
    type: Object,
    required: true,
  },
  platformValidationError: {
    type: String,
    default: '',
  },
})

defineEmits(['platform-change', 'all-platform-change'])

const isAllPlatformSelected = computed(() => props.form.targetPlatforms.includes('all'))
</script>
