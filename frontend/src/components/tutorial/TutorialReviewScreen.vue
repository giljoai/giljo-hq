<template>
  <div class="review-screen">
    <div class="beat-eyebrow">Agent report · done</div>
    <h2 class="beat-title">Your agent proposed this product.</h2>
    <p class="beat-sub">Review the full brief. This becomes the brief every agent reads.</p>

    <div class="review-card" data-testid="tutorial-review-card">
      <div class="review-head">
        <span class="review-name">{{ product?.name || 'Your product' }}</span>
        <div class="head-pills">
          <span v-if="product?.vision_analysis_complete" class="chip chip--vision">Vision doc · generated ✓</span>
          <span class="proposed-pill">PROPOSED BY YOUR AGENT</span>
        </div>
      </div>

      <div v-if="needsName" class="name-fix" data-testid="tutorial-name-required">
        <label class="name-label" for="tutorial-product-name">
          Your agent did not give this product a name. Name it before activating.
        </label>
        <input
          id="tutorial-product-name"
          v-model="nameDraft"
          class="name-input"
          type="text"
          maxlength="200"
          placeholder="Product name"
          data-testid="tutorial-product-name-input"
        />
        <span v-if="nameError" class="name-error" data-testid="tutorial-name-error">{{ nameError }}</span>
      </div>

      <div class="review-body" data-testid="tutorial-review-body">
        <div class="section">
          <div class="section-label">Description</div>
          <p class="review-desc" data-testid="tutorial-review-description">{{ description || 'Not provided' }}</p>
        </div>

        <section
          v-for="section in sections"
          :key="section.key"
          class="acc-section"
          :data-testid="`tutorial-section-${section.key}`"
        >
          <button
            type="button"
            class="acc-head"
            :aria-expanded="expanded[section.key] ? 'true' : 'false'"
            :data-testid="`tutorial-section-toggle-${section.key}`"
            @click="toggle(section.key)"
          >
            <span class="acc-title">{{ section.title }}</span>
            <span class="acc-summary">{{ section.summary }}</span>
            <svg
              class="acc-chevron"
              :class="{ 'acc-chevron--open': expanded[section.key] }"
              width="14"
              height="14"
              viewBox="0 0 14 14"
              fill="none"
              aria-hidden="true"
            >
              <path d="M3.5 5.2L7 8.7l3.5-3.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </button>

          <div v-if="expanded[section.key]" class="acc-fields" :data-testid="`tutorial-section-fields-${section.key}`">
            <div v-for="field in section.fields" :key="field.label" class="field" :class="{ 'field--chips': field.chips }">
              <span class="field-label">{{ field.label }}</span>
              <div v-if="field.chips && field.chips.length" class="chip-row">
                <span v-for="chip in field.chips" :key="chip" class="chip chip--tech">{{ chip }}</span>
              </div>
              <span v-else-if="field.value" class="field-value">{{ field.value }}</span>
              <span v-else class="field-value field-value--empty">Not provided</span>
            </div>
          </div>
        </section>
      </div>
    </div>

    <div class="review-actions">
      <v-btn
        color="primary"
        variant="flat"
        class="activate-btn"
        data-testid="tutorial-activate"
        prepend-icon="mdi-check"
        :disabled="!product || (needsName && !nameDraft.trim())"
        @click="activate"
      >
        Done!
      </v-btn>
    </div>

    <p class="review-post-hint" data-testid="tutorial-review-post-hint">
      You can tune the product later by asking the agent to read back your fields, and modify
      them. Or do it yourself in the app under /products &rsaquo; {{ productDisplayName }}.
    </p>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useProductActivation } from '@/composables/useProductActivation'
import { useProductStore } from '@/stores/products'

const props = defineProps({
  productId: {
    type: String,
    default: null,
  },
})

const emit = defineEmits(['activated'])

const productStore = useProductStore()

const { toggleProductActivation } = useProductActivation(() => productStore.fetchProducts())

const product = computed(() => productStore.getProductById(props.productId))

onMounted(async () => {
  if (!props.productId) return
  try {
    await productStore.fetchProductById(props.productId)
  } catch {
    // getProductById falls back to null when nothing is cached for this id.
  }
})

const description = computed(() => (product.value?.description || '').trim())

const str = (v) => (typeof v === 'string' ? v.trim() : '')

const toChips = (v) =>
  str(v)
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)

const expanded = reactive({ tech: true, architecture: false, standards: false, testing: false })
const toggle = (key) => {
  expanded[key] = !expanded[key]
}

const joinParts = (parts) => parts.filter(Boolean).join(' · ')

const sections = computed(() => {
  const p = product.value || {}
  const ts = p.tech_stack || {}
  const arch = p.architecture || {}
  const tc = p.test_config || {}

  const techFields = [
    { label: 'Languages', chips: toChips(ts.programming_languages) },
    { label: 'Frontend', chips: toChips(ts.frontend_frameworks) },
    { label: 'Backend', chips: toChips(ts.backend_frameworks) },
    { label: 'Databases', chips: toChips(ts.databases_storage) },
    { label: 'Infra', chips: toChips(ts.infrastructure) },
    { label: 'Dev tools', chips: toChips(ts.dev_tools) },
    { label: 'Platforms', chips: (Array.isArray(p.target_platforms) ? p.target_platforms : []).filter(Boolean) },
  ]
  const techGroups = techFields.filter((f) => f.chips.length)
  const techEntries = techGroups.reduce((n, f) => n + f.chips.length, 0)

  const coverage = typeof tc.coverage_target === 'number' ? `${tc.coverage_target}% coverage target` : ''

  return [
    {
      key: 'tech',
      title: 'Tech stack',
      summary: techGroups.length ? `${techGroups.length} groups · ${techEntries} entries` : 'Not provided',
      fields: techFields,
    },
    {
      key: 'architecture',
      title: 'Architecture',
      summary: joinParts([str(arch.primary_pattern), str(arch.api_style)]) || 'Not provided',
      fields: [
        { label: 'Pattern', value: str(arch.primary_pattern) },
        { label: 'API style', value: str(arch.api_style) },
        { label: 'Design patterns', value: str(arch.design_patterns) },
        { label: 'Notes', value: str(arch.architecture_notes) },
      ],
    },
    {
      key: 'standards',
      title: 'Standards',
      summary:
        joinParts([
          str(arch.coding_conventions) && 'conventions',
          str(p.brand_guidelines) && 'brand',
          str(tc.quality_standards) && 'quality',
        ]) || 'Not provided',
      fields: [
        { label: 'Coding conventions', value: str(arch.coding_conventions) },
        { label: 'Brand guidelines', value: str(p.brand_guidelines) },
        { label: 'Quality standards', value: str(tc.quality_standards) },
      ],
    },
    {
      key: 'testing',
      title: 'Testing',
      summary: joinParts([str(tc.test_strategy), str(tc.testing_frameworks), coverage]) || 'Not provided',
      fields: [
        { label: 'Strategy', value: str(tc.test_strategy) },
        { label: 'Frameworks', value: str(tc.testing_frameworks) },
        { label: 'Coverage target', value: typeof tc.coverage_target === 'number' ? `${tc.coverage_target}%` : '' },
      ],
    },
  ]
})

const nameDraft = ref('')
const nameError = ref('')

const needsName = computed(() => Boolean(product.value) && !(product.value.name || '').trim())

const productDisplayName = computed(() => (product.value?.name || '').trim() || 'your product')

async function activate() {
  if (!product.value) return

  if (needsName.value) {
    const name = nameDraft.value.trim()
    if (!name) return
    nameError.value = ''
    try {
      await productStore.updateProduct(product.value.id, { name })
    } catch {
      nameError.value = 'Could not save that name. Check your connection and try again.'
      return
    }
  }

  if (product.value.is_active) {
    emit('activated')
    return
  }
  await toggleProductActivation(product.value)
  emit('activated')
}
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

.review-screen {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.name-fix {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px 18px 0;
  flex-shrink: 0;
}

.name-label {
  font-size: 12px;
  color: var(--text-secondary);
}

.name-input {
  background: $color-background-primary;
  border-radius: $border-radius-default;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.14);
  padding: 8px 10px;
  font-family: inherit;
  font-size: 13px;
  color: $color-text-primary;

  &:focus-visible {
    outline: 2px solid rgba($color-brand-yellow, 0.55);
    outline-offset: 1px;
  }
}

.name-error {
  font-size: 11.5px;
  color: $color-status-error;
}

.beat-eyebrow {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.2em;
  color: $color-agent-researcher;
  text-transform: uppercase;
  margin-bottom: 10px;
}

.beat-title {
  margin: 0 0 6px;
  font-family: 'Outfit', $typography-font-primary;
  font-weight: 700;
  font-size: 26px;
  letter-spacing: -0.02em;
  color: $color-text-primary;
}

.beat-sub {
  margin: 0 0 14px;
  font-size: 14px;
  line-height: 1.55;
  color: var(--text-secondary);
}

/* The card owns the remaining height; its BODY scrolls, so a long proposal
   can never push the Activate bar off screen. */
.review-card {
  background: $elevation-raised;
  border-radius: $border-radius-rounded;
  box-shadow: inset 0 0 0 1px rgba($color-agent-researcher, 0.35);
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.review-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 15px 18px 12px;
  box-shadow: inset 0 -1px 0 rgba(255, 255, 255, 0.06);
  flex-shrink: 0;
}

.head-pills {
  display: flex;
  align-items: center;
  gap: 8px;
}

.review-name {
  font-family: 'Outfit', $typography-font-primary;
  font-weight: 600;
  font-size: 17px;
  color: $color-text-primary;
}

.proposed-pill {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 9.5px;
  color: $color-agent-researcher;
  background: rgba($color-agent-researcher, 0.12);
  padding: 4px 10px;
  border-radius: $border-radius-pill;
  white-space: nowrap;
}

.review-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 14px 18px 18px;
  display: flex;
  flex-direction: column;
}

.section {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding-bottom: 14px;
}

.section-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--text-muted);
}

.review-desc {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--text-secondary);
  white-space: pre-line;
}

.acc-section {
  display: flex;
  flex-direction: column;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.06);
}

.acc-head {
  display: flex;
  align-items: baseline;
  gap: 12px;
  padding: 12px 2px;
  background: none;
  border: 0;
  cursor: pointer;
  text-align: left;
  width: 100%;
  font: inherit;

  &:focus-visible {
    outline: 2px solid rgba($color-brand-yellow, 0.55);
    outline-offset: 1px;
    border-radius: $border-radius-default;
  }
}

.acc-title {
  font-family: 'Outfit', $typography-font-primary;
  font-weight: 600;
  font-size: 13px;
  color: $color-text-primary;
  flex-shrink: 0;
}

.acc-summary {
  font-size: 11.5px;
  color: var(--text-muted);
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.acc-chevron {
  color: var(--text-muted);
  align-self: center;
  flex-shrink: 0;
  transition: transform 0.15s ease;
}

.acc-chevron--open {
  transform: rotate(180deg);
}

.acc-fields {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 2px 2px 14px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.field--chips {
  flex-direction: row;
  align-items: center;
  gap: 10px;
}

.field-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 10px;
  color: var(--text-muted);
}

.field--chips .field-label {
  width: 88px;
  flex-shrink: 0;
}

.field-value {
  font-size: 12.5px;
  color: $color-text-primary;
}

.field-value--empty {
  color: var(--text-muted);
  font-style: italic;
}

.chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}

.chip {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 10.5px;
  padding: 5px 10px;
  border-radius: $border-radius-pill;
}

.chip--tech {
  color: $color-agent-implementor;
  background: rgba($color-agent-implementor, 0.12);
}

.chip--vision {
  color: $color-agent-researcher;
  background: rgba($color-agent-researcher, 0.12);
  font-size: 10px;
  white-space: nowrap;
}

.review-actions {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-top: 14px;
  flex-shrink: 0;
}

.activate-btn {
  font-family: 'Outfit', $typography-font-primary;
  font-weight: 600;
  font-size: 13.5px;
  border-radius: $border-radius-default;
  flex-shrink: 0;
  background: $color-brand-yellow !important;
  color: $color-on-yellow-ink !important;

  &:hover {
    background: $color-brand-yellow-hover !important;
  }
}

.review-post-hint {
  margin: 10px 0 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-muted);
}
</style>
