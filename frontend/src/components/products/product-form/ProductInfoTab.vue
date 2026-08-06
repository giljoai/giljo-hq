<template>
  <div data-testid="product-form-panel-info">
    <div class="text-body-large mb-1">Product Information</div>
    <div class="text-body-small text-warning mb-4">Always used as context source by orchestrator.</div>

    <v-text-field
      v-model="form.projectPath"
      label="Codebase Folder (optional)"
      variant="outlined"
      density="comfortable"
      placeholder="e.g., C:\Projects\MyApp or /home/user/myapp"
      prepend-icon="mdi-folder-outline"
      hint="Your local codebase path"
      persistent-hint
      class="mb-4"
    ></v-text-field>

    <v-textarea
      v-model="form.description"
      label="Product Description"
      variant="outlined"
      density="comfortable"
      rows="6"
      auto-grow
      hint="Describe what this product does and its purpose"
      persistent-hint
      class="mb-4"
    ></v-textarea>

    <v-textarea
      v-model="form.coreFeatures"
      hint="Main functionality and capabilities of this product"
      persistent-hint
      variant="outlined"
      density="comfortable"
      rows="4"
      auto-grow
      class="mb-4"
    >
      <template #label>
        <span>Core Product Features</span>
      </template>
    </v-textarea>

    <v-textarea
      v-model="form.brandGuidelines"
      hint="Describe your visual style, colors, and fonts, or provide a path/URL to your brand guide. Agents use this when creating frontend components."
      persistent-hint
      variant="outlined"
      density="comfortable"
      rows="4"
      auto-grow
      class="mb-4"
    >
      <template #label>
        <span>Brand & Design Guidelines</span>
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
