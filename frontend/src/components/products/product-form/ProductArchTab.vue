<template>
  <div data-testid="product-form-panel-arch">
    <div class="text-body-large mb-1">Architecture & Design Patterns</div>
    <div class="text-body-small text-warning mb-4">
      Optionally included as context source by orchestrator.
      <v-chip size="x-small" color="success" variant="tonal" class="ml-2">Activated in Context Manager</v-chip>
    </div>

    <v-textarea
      v-for="field in FIELDS"
      :key="field.key"
      v-model="form.architecture[field.key]"
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
  </div>
</template>

<script setup>
const FIELDS = [
  { key: 'primary_pattern', label: 'Primary Architecture Pattern', placeholder: 'Modular Monolith with Event-Driven components, CQRS for high-traffic modules', hint: 'Describe the overall system architecture approach', rows: '2' },
  { key: 'design_patterns', label: 'Design Patterns & Principles', placeholder: 'Repository Pattern, Dependency Injection, Factory Pattern, SOLID principles', hint: 'List design patterns and architectural principles used', rows: '3' },
  { key: 'api_style', label: 'API Style & Communication', placeholder: 'REST API (OpenAPI 3.0), WebSocket for real-time updates, GraphQL for complex queries', hint: 'Describe API communication patterns and protocols', rows: '2' },
  { key: 'architecture_notes', label: 'Architecture Notes', hint: 'Additional architectural decisions, constraints, or context', rows: '4' },
  { key: 'coding_conventions', label: 'Coding Conventions & Standards', hint: 'Define naming conventions, error handling patterns, code style rules, and other standards agents should follow when writing code', rows: '6' },
]

defineProps({
  form: {
    type: Object,
    required: true,
  },
})
</script>
