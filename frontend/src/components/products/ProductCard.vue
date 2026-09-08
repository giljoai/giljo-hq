<template>
  <v-card variant="flat" class="product-card h-100 smooth-border" data-testid="product-card" :data-product-id="product.id">
    <v-card-text>
      <div class="d-flex align-start justify-space-between mb-2 product-title-row">
        <div
          class="text-title-large product-title-clamp"
          :class="{ 'text-primary': isActive }"
          :title="product.name"
        >
          {{ product.name }}
        </div>
        <span
          v-if="isActive"
          class="product-status-chip product-status-active"
        >
          Shown
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
      <v-row dense class="product-stats-row">
        <v-col cols="4" class="text-center product-stat-col">
          <div class="text-body-small text-muted-a11y product-stat-label">Tasks</div>
          <div class="text-title-large product-text-secondary">
            {{ product.task_count || 0 }}
          </div>
        </v-col>
        <v-col cols="4" class="text-center product-stat-col">
          <div class="text-body-small text-muted-a11y product-stat-label">Projects</div>
          <div class="text-title-large product-text-secondary">
            {{ product.project_count || 0 }}
          </div>
        </v-col>
        <v-col cols="4" class="text-center product-stat-col">
          <div class="text-body-small text-muted-a11y product-stat-label">Completed</div>
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

    <v-card-actions class="justify-center product-actions-footer">
      <v-tooltip location="top" content-class="branded-tooltip" max-width="260">
        <template #activator="{ props }">
          <div v-bind="props" class="default-product-control">
            <v-checkbox
              :model-value="isDefault"
              density="compact"
              hide-details
              color="primary"
              class="default-product-checkbox"
              :aria-label="isDefault ? 'Default product' : 'Set as default product'"
              data-testid="product-card-default"
              @update:model-value="onDefaultToggle"
            />
            <span class="text-body-small default-product-label">Default</span>
          </div>
        </template>
        <span>Where reads go when nothing else is specified. Agents must always name a product when writing.</span>
      </v-tooltip>
      <v-tooltip location="top" content-class="branded-tooltip">
        <template #activator="{ props }">
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
        <template #activator="{ props }">
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
        <template #activator="{ props }">
          <v-btn
            icon
            size="small"
            variant="text"
            v-bind="props"
            class="icon-interactive-play"
            :aria-label="isActive ? 'Hide product' : 'Show product'"
            data-testid="product-card-activation"
            @click="$emit('toggle-activation', product)"
          >
            <v-icon>{{ isActive ? 'mdi-eye-off-outline' : 'mdi-eye-outline' }}</v-icon>
          </v-btn>
        </template>
        <span>{{ isActive ? 'Hide Product' : 'Show Product' }}</span>
      </v-tooltip>
      <v-tooltip location="top" content-class="branded-tooltip">
        <template #activator="{ props }">
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
        <template #activator="{ props }">
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
  // FE-9529: whether THIS product is the resolved DEFAULT (where an unscoped
  // read goes) -- independent of isActive/shown-hidden (D2: a hidden product
  // is still a fully valid default). Callers must pass the RESOLVED default
  // (e.g. productStore.activeProduct), not the row's raw is_default column:
  // a tenant's sole product can be the real fallback target while its own
  // is_default is still false (never auto-set on create), and rendering the
  // raw column there would show an unticked box on a tenant whose reads
  // plainly work.
  isDefault: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['info', 'tune', 'edit', 'delete', 'toggle-activation', 'set-default'])

const { formatDate } = useFormatDate()

// Exactly one default exists tenant-wide (DB-enforced) -- this is a
// radio-like single selection, not an independent per-card toggle. Clicking
// an already-checked box is a no-op (there is no "unset the default", only
// "move it elsewhere"); the checkbox stays checked because it is driven by
// the isDefault prop, not local state.
function onDefaultToggle(value) {
  if (value && !props.isDefault) {
    emit('set-default', props.product)
  }
}

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

// FE-9571: the card's layout system. v-card is already display:flex;
// flex-direction:column by Vuetify default, and v-card-text already carries
// flex:1 1 auto -- but that alone left the footer's resting position varying
// by up to ~76px between cards with different content volumes (a "Test" card
// with no vision chips floated its actions row well above a card that had
// them). `margin-top: auto` on the actions row is the robust flex-column
// pinning idiom: it claims 100% of the leftover space above itself inside the
// column, which pins it to the card's bottom edge regardless of how much (or
// how little) v-card-text's own content grows -- fixing symptom 4 (footer not
// pinned to bottom, misaligned across cards of different content heights)
// without depending on flex-grow distribution nuances.
.product-card {
  display: flex;
  flex-direction: column;
  transition: all $transition-slow ease;
  border-radius: $border-radius-md;
  --smooth-border-color: rgba(255, 255, 255, 0.18);
}

.product-card:hover {
  transform: translateY(-2px);
  --smooth-border-color: rgba(255, 255, 255, 0.28);
}

.product-card :deep(.v-card-text) {
  flex: 1 1 auto;
  min-height: 0;
}

/* Lighter divider line (25% closer to white) */
.product-divider {
  opacity: 0.3;
  border-color: rgba(255, 255, 255, 0.6);
}

// FE-9571: the actions row's 6 controls (Default checkbox+label, info, tune,
// visibility, edit, delete) need ~260px but a 4-up card at common breakpoints
// is only ~200-230px wide. With no wrap, `justify-center`'s unsafe overflow
// spilled the excess symmetrically past BOTH edges of the card, and the
// card's own `overflow: hidden` (Vuetify default, for the rounded corners)
// clipped it there: ~19px off the leading edge ate into the Default checkbox
// and label (symptom 2, "Defaul" + the info icon crowding it), and ~19px off
// the trailing edge left only a sliver of the Delete button visible (symptom
// 3 -- the pink/magenta strip is the "error"-colored delete control per
// theme.js, not a stray decoration; it was a functional control that had
// become nearly invisible AND nearly unclickable). Wrapping instead of
// clipping is the deliberate, width-independent fix: whatever doesn't fit on
// one line reflows to a second, fully visible line, so nothing is ever
// silently cut off at any card width (verified at the reported ~1249px width
// and at the mobile/tablet presets).
.product-card :deep(.product-actions-footer) {
  padding-top: 4px;
  flex: 0 0 auto;
  flex-wrap: wrap;
  row-gap: 4px;
  margin-top: auto;
}

.default-product-control {
  display: flex;
  align-items: center;
  gap: 2px;
  cursor: pointer;
  min-width: 0;
}

.default-product-checkbox {
  flex: 0 0 auto;
}

.default-product-checkbox :deep(.v-selection-control) {
  min-height: 0;
}

.default-product-label {
  color: var(--text-secondary);
  white-space: nowrap;
}

// FE-9571: title/chip row. The row was `align-center`, which vertically
// centers the "Shown" chip against the FULL height of the title block --
// harmless for a one-line title, but for a long name wrapping to 2-3 lines
// (e.g. "ZZ TEST CARD - DELETE ME (Giljo HQ audit dry-run)") that put the
// chip mid-title instead of level with the first line (symptom 5). Top-
// aligning the row plus clamping the title to 2 lines with an ellipsis keeps
// the chip anchored to the first line and keeps card height predictable
// regardless of name length; the full name is still available via the
// native `title` tooltip attribute added on the template.
.product-title-row {
  gap: 8px;
}

.product-title-clamp {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-width: 0;
  flex: 1 1 auto;
  word-break: break-word;
}

/* Tinted status chip for Active badge */
.product-status-chip {
  display: inline-flex;
  align-items: center;
  flex: 0 0 auto;
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

// FE-9571: "Completed" (9 characters) was splitting mid-word into "Complet" /
// "ed" inside its 1-of-3 stat column. Vuetify's base `.v-card` rule sets
// `overflow-wrap: break-word` globally (for the Product ID hash truncation
// elsewhere in this same card, which wants exactly that), and that same
// break-word behavior was inherited by these single-word stat labels, so the
// browser split "Completed" as soon as it was even a pixel too wide for the
// column rather than letting it wrap between words (it has none) or simply
// take the extra pixel. Scoping `overflow-wrap: normal` + `word-break:
// keep-all` to just the stat labels stops mid-word splitting there without
// touching the Product ID hash's own break-word need.
.product-stat-col {
  min-width: 0;
}

.product-stat-label {
  overflow-wrap: normal;
  word-break: keep-all;
  white-space: normal;
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
