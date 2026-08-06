<template>
  <div data-testid="product-form-panel-tech">
    <div class="text-body-large mb-1">Technology Stack Configuration</div>
    <div class="text-body-small text-warning mb-4">
      Optionally included as context source by orchestrator.
      <v-chip size="x-small" color="success" variant="tonal" class="ml-2">Activated in Context Manager</v-chip>
    </div>

    <v-textarea
      v-model="form.techStack.programming_languages"
      placeholder="Python 3.11, JavaScript ES2023, TypeScript 5.2"
      hint="List all programming languages used (comma-separated or line-by-line)"
      persistent-hint
      variant="outlined"
      density="comfortable"
      rows="3"
      auto-grow
      class="mb-4"
    >
      <template #label>
        <span>Programming Languages</span>
      </template>
    </v-textarea>

    <v-textarea
      v-model="form.techStack.frontend_frameworks"
      placeholder="Vue 3, Vuetify 3, Pinia, Vue Router"
      hint="List frontend technologies (frameworks, libraries, tools)"
      persistent-hint
      variant="outlined"
      density="comfortable"
      rows="3"
      auto-grow
      class="mb-4"
    >
      <template #label>
        <span>Frontend Frameworks & Libraries</span>
      </template>
    </v-textarea>

    <v-textarea
      v-model="form.techStack.backend_frameworks"
      placeholder="FastAPI 0.104, SQLAlchemy 2.0, Alembic, asyncio"
      hint="List backend technologies (frameworks, ORMs, services)"
      persistent-hint
      variant="outlined"
      density="comfortable"
      rows="3"
      auto-grow
      class="mb-4"
    >
      <template #label>
        <span>Backend Frameworks & Services</span>
      </template>
    </v-textarea>

    <v-textarea
      v-model="form.techStack.databases_storage"
      placeholder="PostgreSQL 16, Redis 7, Vector embeddings (pgvector)"
      hint="List databases and data storage solutions"
      persistent-hint
      variant="outlined"
      density="comfortable"
      rows="3"
      auto-grow
      class="mb-4"
    >
      <template #label>
        <span>Databases & Data Storage</span>
      </template>
    </v-textarea>

    <v-textarea
      v-model="form.techStack.infrastructure"
      placeholder="Docker, Kubernetes, GitHub Actions CI/CD, AWS (EC2, S3, RDS)"
      hint="List infrastructure and deployment tools"
      persistent-hint
      variant="outlined"
      density="comfortable"
      rows="3"
      auto-grow
      class="mb-4"
    >
      <template #label>
        <span>Infrastructure & DevOps</span>
      </template>
    </v-textarea>

    <!-- Target Platform(s) - Handover 0425 Phase 2 -->
    <div class="mb-4">
      <label class="text-title-small mb-2 d-block">Target Platform(s)</label>
      <div class="text-body-small text-muted-a11y mb-3">
        Select the operating systems this product is designed for
      </div>

      <div class="d-flex flex-wrap ga-3">
        <v-checkbox
          v-model="form.targetPlatforms"
          value="windows"
          label="Windows"
          hide-details
          density="comfortable"
          :disabled="isAllPlatformSelected"
          @update:model-value="$emit('platform-change')"
        />
        <v-checkbox
          v-model="form.targetPlatforms"
          value="linux"
          label="Linux"
          hide-details
          density="comfortable"
          :disabled="isAllPlatformSelected"
          @update:model-value="$emit('platform-change')"
        />
        <v-checkbox
          v-model="form.targetPlatforms"
          value="macos"
          label="macOS"
          hide-details
          density="comfortable"
          :disabled="isAllPlatformSelected"
          @update:model-value="$emit('platform-change')"
        />
        <v-checkbox
          v-model="form.targetPlatforms"
          value="android"
          label="Android"
          hide-details
          density="comfortable"
          :disabled="isAllPlatformSelected"
          @update:model-value="$emit('platform-change')"
        />
        <v-checkbox
          v-model="form.targetPlatforms"
          value="ios"
          label="iOS"
          hide-details
          density="comfortable"
          :disabled="isAllPlatformSelected"
          @update:model-value="$emit('platform-change')"
        />
        <v-checkbox
          v-model="form.targetPlatforms"
          value="web"
          label="Web"
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
