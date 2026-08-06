<template>
  <div data-testid="product-form-panel-arch">
    <div class="text-body-large mb-1">Architecture & Design Patterns</div>
    <div class="text-body-small text-warning mb-4">
      Optionally included as context source by orchestrator.
      <v-chip size="x-small" color="success" variant="tonal" class="ml-2">Activated in Context Manager</v-chip>
    </div>

    <v-textarea
      v-model="form.architecture.primary_pattern"
      placeholder="Modular Monolith with Event-Driven components, CQRS for high-traffic modules"
      hint="Describe the overall system architecture approach"
      persistent-hint
      variant="outlined"
      density="comfortable"
      rows="2"
      auto-grow
      class="mb-4"
    >
      <template #label>
        <span>Primary Architecture Pattern</span>
      </template>
    </v-textarea>

    <v-textarea
      v-model="form.architecture.design_patterns"
      placeholder="Repository Pattern, Dependency Injection, Factory Pattern, SOLID principles"
      hint="List design patterns and architectural principles used"
      persistent-hint
      variant="outlined"
      density="comfortable"
      rows="3"
      auto-grow
      class="mb-4"
    >
      <template #label>
        <span>Design Patterns & Principles</span>
      </template>
    </v-textarea>

    <v-textarea
      v-model="form.architecture.api_style"
      placeholder="REST API (OpenAPI 3.0), WebSocket for real-time updates, GraphQL for complex queries"
      hint="Describe API communication patterns and protocols"
      persistent-hint
      variant="outlined"
      density="comfortable"
      rows="2"
      auto-grow
      class="mb-4"
    >
      <template #label>
        <span>API Style & Communication</span>
      </template>
    </v-textarea>

    <v-textarea
      v-model="form.architecture.architecture_notes"
      hint="Additional architectural decisions, constraints, or context"
      persistent-hint
      variant="outlined"
      density="comfortable"
      rows="4"
      auto-grow
      class="mb-4"
    >
      <template #label>
        <span>Architecture Notes</span>
      </template>
    </v-textarea>

    <v-textarea
      v-model="form.architecture.coding_conventions"
      hint="Define naming conventions, error handling patterns, code style rules, and other standards agents should follow when writing code"
      persistent-hint
      variant="outlined"
      density="comfortable"
      rows="6"
      auto-grow
      class="mb-4"
    >
      <template #label>
        <span>Coding Conventions & Standards</span>
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
</script>
