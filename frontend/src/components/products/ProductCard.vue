<template>
  <v-card variant="flat" class="product-card h-100 smooth-border" data-testid="product-card" :data-product-id="product.id">
    <v-card-text>
      <div class="d-flex align-center justify-space-between mb-2">
        <div
          class="text-title-large"
          :class="{ 'text-primary': isActive }"
        >
          {{ product.name }}
        </div>
        <span
          v-if="isActive"
          class="product-status-chip product-status-active"
        >
          Active
        </span>
      </div>

      <div class="text-body-small text-muted-a11y" :class="{ 'mb-1': product.updated_at, 'mb-3': !product.updated_at }">
        Created: {{ formatDate(product.created_at) }}
      </div>
      <div v-if="product.updated_at" class="text-body-small text-muted-a11y mb-3">
        Context updated: {{ formatDate(product.updated_at) }}
      </div>

      <div class="mb-3">
        <div class="text-body-small text-muted-a11y">Product ID:</div>
        <div
          class="font-monospace text-muted-a11y"
          style="font-size: 0.65rem; word-break: break-all; line-height: 1.3"
        >
          {{ product.id }}
        </div>
      </div>

      <!-- Statistics -->
      <v-divider class="my-3 product-divider"></v-divider>
      <v-row dense>
        <v-col cols="4" class="text-center">
          <div class="text-body-small text-muted-a11y">Tasks</div>
          <div class="text-title-large product-text-secondary">
            {{ product.task_count || 0 }}
          </div>
        </v-col>
        <v-col cols="4" class="text-center">
          <div class="text-body-small text-muted-a11y">Projects</div>
          <div class="text-title-large product-text-secondary">
            {{ product.project_count || 0 }}
          </div>
        </v-col>
        <v-col cols="4" class="text-center">
          <div class="text-body-small text-muted-a11y">Completed</div>
          <div class="text-title-large product-text-secondary">
            {{ completedProjectsCount }}
          </div>
        </v-col>
      </v-row>

      <!-- Vision Document Status (Handover 0347; BE-6066 P4: aggregates) -->
      <div v-if="visionDocCount > 0" class="mt-2 d-flex ga-1 flex-wrap">
        <span
          class="vision-chip"
          :style="visionChunkedCount > 0 ? 'background: rgba(103,189,109,0.15); color: var(--color-accent-success)' : 'background: rgba(255,152,0,0.15); color: var(--status-blocked)'"
        >
          <v-icon size="12" class="mr-1">mdi-file-document</v-icon>
          {{ visionDocCount }} docs
        </span>
        <span
          v-if="visionChunkedCount > 0"
          class="vision-chip"
          style="background: var(--agent-implementor-tinted); color: var(--agent-implementor-primary)"
        >
          <v-icon size="12" class="mr-1">mdi-database</v-icon>
          {{ visionTotalChunks }} chunks
        </span>
        <!-- BE-5118: AI analysis aggregate state -->
        <span
          class="vision-chip smooth-border"
          :style="analysisPillStyle"
        >
          <v-icon size="12" class="mr-1">{{
            product.vision_analysis_complete ? 'mdi-check-circle' : 'mdi-clock-outline'
          }}</v-icon>
          {{ analysisPillLabel }}
        </span>
      </div>
    </v-card-text>

    <v-card-actions class="justify-center">
      <v-tooltip location="top" content-class="branded-tooltip">
        <template v-slot:activator="{ props }">
          <v-btn
            icon
            size="small"
            variant="text"
            v-bind="props"
            class="icon-interactive"
            aria-label="View product details"
            data-testid="product-card-info"
            @click="$emit('info', product)"
          >
            <v-icon>mdi-information-outline</v-icon>
          </v-btn>
        </template>
        <span>View Product Details</span>
      </v-tooltip>
      <v-tooltip location="top" content-class="branded-tooltip">
        <template v-slot:activator="{ props }">
          <v-btn
            icon
            size="small"
            variant="text"
            v-bind="props"
            class="icon-interactive"
            aria-label="Tune context"
            data-testid="product-card-tune"
            @click="$emit('tune', product)"
          >
            <v-icon>mdi-tune</v-icon>
          </v-btn>
        </template>
        <span>Tune Context</span>
      </v-tooltip>
      <v-tooltip location="top" content-class="branded-tooltip">
        <template v-slot:activator="{ props }">
          <v-btn
            icon
            size="small"
            variant="text"
            v-bind="props"
            class="icon-interactive-play"
            :aria-label="isActive ? 'Deactivate product' : 'Activate product'"
            data-testid="product-card-activation"
            @click="$emit('toggle-activation', product)"
          >
            <v-icon>{{ isActive ? 'mdi-stop' : 'mdi-play' }}</v-icon>
          </v-btn>
        </template>
        <span>{{ isActive ? 'Deactivate Product' : 'Activate Product' }}</span>
      </v-tooltip>
      <v-tooltip location="top" content-class="branded-tooltip">
        <template v-slot:activator="{ props }">
          <v-btn
            icon
            size="small"
            variant="text"
            v-bind="props"
            class="icon-interactive"
            aria-label="Edit product"
            data-testid="product-card-edit"
            @click="$emit('edit', product)"
          >
            <v-icon>mdi-pencil</v-icon>
          </v-btn>
        </template>
        <span>Edit Product</span>
      </v-tooltip>
      <v-tooltip location="top" content-class="branded-tooltip">
        <template v-slot:activator="{ props }">
          <v-btn
            icon
            size="small"
            variant="text"
            color="error"
            v-bind="props"
            aria-label="Delete product"
            data-testid="product-card-delete"
            @click="$emit('delete', product)"
          >
            <v-icon>mdi-delete</v-icon>
          </v-btn>
        </template>
        <span>Delete Product</span>
      </v-tooltip>
    </v-card-actions>
  </v-card>
</template>

<script setup>
import { computed } from 'vue'
import { useFormatDate } from '@/composables/useFormatDate'
import { hexToRgba } from '@/utils/colorUtils'
import { getStatusColor } from '@/utils/statusConfig'
import { getAgentColor } from '@/config/agentColors'

const props = defineProps({
  product: {
    type: Object,
    required: true,
  },
  isActive: {
    type: Boolean,
    default: false,
  },
})

defineEmits(['info', 'tune', 'edit', 'delete', 'toggle-activation'])

const { formatDate } = useFormatDate()

const completedProjectsCount = computed(() => {
  const totalProjects = props.product.project_count || 0
  const unfinishedProjects = props.product.unfinished_projects || 0
  return Math.max(0, totalProjects - unfinishedProjects)
})

// BE-6066 P4: the products LIST no longer ships the full vision_documents
// array — the backend pre-aggregates it into product.vision_summary
// {doc_count, chunked_count, chunk_total, embedded_count}, mirroring the exact
// semantics these computeds used to derive client-side. Full per-doc detail
// loads on demand when the user opens Details/Edit.
const visionDocCount = computed(() => props.product.vision_summary?.doc_count || 0)
const visionChunkedCount = computed(() => props.product.vision_summary?.chunked_count || 0)
const visionTotalChunks = computed(() => props.product.vision_summary?.chunk_total || 0)

// BE-5118: product-level vision-analysis aggregate pill helpers
const ANALYSIS_GREEN = getStatusColor('complete')
const ANALYSIS_YELLOW = getAgentColor('tester').hex

const analysisPillLabel = computed(() => {
  if (props.product.vision_analysis_complete) return 'Analyzed'
  const total = visionDocCount.value
  const analyzed = props.product.vision_summary?.embedded_count || 0
  if (total === 0 || analyzed === 0) return 'Pending analysis'
  return `Pending analysis — ${analyzed} of ${total} docs analyzed`
})

const analysisPillStyle = computed(() => {
  const hex = props.product.vision_analysis_complete ? ANALYSIS_GREEN : ANALYSIS_YELLOW
  return {
    background: hexToRgba(hex, 0.15),
    color: hex,
    '--smooth-border-color': hexToRgba(hex, 0.45),
  }
})
</script>

<style lang="scss">
@use '../../styles/design-tokens' as *;
/* Global branded tooltips — must be unscoped to affect tooltip portal overlays.
   Previously in ProductsView.vue; moved here with the card (FE-6006 unit 3b). */
.branded-tooltip {
  background-color: rgba(255, 195, 0, 0.95) !important; /* !important: unscoped — must override Vuetify tooltip defaults */
  color: rgb(var(--v-theme-on-primary)) !important; /* !important: unscoped — must override Vuetify tooltip defaults */
  font-weight: 500;
  font-size: 0.875rem;
  padding: 6px 12px;
  border-radius: $border-radius-sharp;
}
</style>

<style lang="scss" scoped>
@use '../../styles/design-tokens' as *;

.product-card {
  transition: all $transition-slow ease;
  border-radius: $border-radius-md;
  --smooth-border-color: rgba(255, 255, 255, 0.18);
}

.product-card:hover {
  transform: translateY(-2px);
  --smooth-border-color: rgba(255, 255, 255, 0.28);
}

/* Lighter divider line (25% closer to white) */
.product-divider {
  opacity: 0.3;
  border-color: rgba(255, 255, 255, 0.6);
}

/* Reduce spacing above card actions by 50% */
.product-card :deep(.v-card-actions) {
  padding-top: 4px;
}

/* Tinted status chip for Active badge */
.product-status-chip {
  display: inline-flex;
  align-items: center;
  font-size: 0.7rem;
  font-weight: 600;
  padding: 2px 10px;
  border-radius: $border-radius-pill;
  line-height: 1.4;
  letter-spacing: 0.02em;
}

.product-status-active {
  background: rgba($color-accent-success, 0.15);
  color: $color-accent-success;
}

.product-text-secondary {
  color: var(--text-secondary) !important; /* !important: override Vuetify text color classes on same element */
}

/* Vision doc tinted chips */
.vision-chip {
  display: inline-flex;
  align-items: center;
  font-size: 0.65rem;
  font-weight: 600;
  padding: 1px 8px;
  border-radius: $border-radius-sharp;
  line-height: 1.5;
}
</style>
