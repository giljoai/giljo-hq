<template>
  <div data-testid="product-form-panel-testing">
    <div class="text-body-large mb-1">Quality Standards & Testing Configuration</div>
    <div class="text-body-small text-warning mb-4">
      Optionally included as context source by orchestrator.
      <v-chip size="x-small" color="success" variant="tonal" class="ml-2">Activated in Context Manager</v-chip>
    </div>

    <v-textarea
      v-model="form.testConfig.quality_standards"
      placeholder="e.g., Code review required, 80% coverage, zero critical bugs, all tests passing before merge"
      hint="Define your quality expectations for testing and development"
      persistent-hint
      variant="outlined"
      density="comfortable"
      rows="4"
      auto-grow
      class="mb-4"
    >
      <template #label>
        <span>Quality Standards</span>
      </template>
    </v-textarea>

    <v-select
      v-model="form.testConfig.test_strategy"
      :items="testingStrategies"
      item-title="title"
      item-value="value"
      hint="Choose the primary testing methodology for this product"
      persistent-hint
      variant="outlined"
      density="comfortable"
      class="mb-4"
    >
      <template #label>
        <span>Testing Strategy & Approach</span>
      </template>

      <template #item="{ props: itemProps, item }">
        <v-list-item v-bind="itemProps">
          <template #prepend>
            <v-icon :icon="item.icon" class="mr-2"></v-icon>
          </template>
          <v-list-item-title>{{ item.title }}</v-list-item-title>
          <v-list-item-subtitle>{{ item.subtitle }}</v-list-item-subtitle>
        </v-list-item>
      </template>

      <template #selection="{ item }">
        <div class="d-flex align-center">
          <v-icon :icon="item.icon" size="small" class="mr-2"></v-icon>
          <span>{{ item.title }}</span>
        </div>
      </template>
    </v-select>

    <div class="mb-4">
      <label class="text-body-small text-muted-a11y">
        Test Coverage Target: {{ form.testConfig.coverage_target }}%
      </label>
      <v-slider
        v-model="form.testConfig.coverage_target"
        min="0"
        max="100"
        step="5"
        thumb-label
        color="primary"
      ></v-slider>
    </div>

    <v-textarea
      v-model="form.testConfig.testing_frameworks"
      placeholder="pytest, pytest-asyncio, Playwright, coverage.py"
      hint="List testing frameworks and quality assurance tools"
      persistent-hint
      variant="outlined"
      density="comfortable"
      rows="3"
      auto-grow
      class="mb-4"
    >
      <template #label>
        <span>Testing Frameworks & Tools</span>
      </template>
    </v-textarea>
  </div>
</template>

<script setup>
defineProps({
  form: {
    type: Object,
    required: true,
  },
})

const testingStrategies = [
  { value: 'TDD', title: 'TDD (Test-Driven Development)', subtitle: 'Write tests before implementation code', icon: 'mdi-test-tube' },
  { value: 'BDD', title: 'BDD (Behavior-Driven Development)', subtitle: 'Tests based on user stories and behavior specs', icon: 'mdi-comment-text-multiple' },
  { value: 'Integration-First', title: 'Integration-First', subtitle: 'Focus on testing component interactions', icon: 'mdi-connection' },
  { value: 'E2E-First', title: 'E2E-First', subtitle: 'Prioritize end-to-end user workflow tests', icon: 'mdi-path' },
  { value: 'Manual', title: 'Manual Testing', subtitle: 'User-driven QA and exploratory testing', icon: 'mdi-human-male' },
  { value: 'Hybrid', title: 'Hybrid Approach', subtitle: 'Combination of multiple testing strategies', icon: 'mdi-view-grid-plus' },
]
</script>
