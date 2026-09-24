<template>
  <div>
    <div class="tab-header mb-4 d-flex align-center">
      <h2 class="text-title-large">Agent behaviour</h2>
      <v-tooltip location="bottom" max-width="360">
        <template #activator="{ props: tipProps }">
          <v-icon v-bind="tipProps" size="small" class="ml-2" color="medium-emphasis"
            >mdi-help-circle-outline</v-icon
          >
        </template>
        <span
          >Settings that modify how agents operate in the application. They belong to your
          account, not to a product, so every product runs under the same five answers. Each one
          saves the moment you change it.</span
        >
      </v-tooltip>
    </div>
    <p class="text-body-medium text-muted-a11y mb-4">
      How agents behave for this account. Applies to every product. Changes save as you make them.
    </p>

    <v-card variant="flat" class="smooth-border behaviour-card">
      <v-card-text>
        <div class="setting-rows">
          <ExecutionModeDefaultSelect />
          <AgentTimingSettings />
          <OrchestrationToggles />
        </div>
      </v-card-text>
    </v-card>
  </div>
</template>

<script setup>
import ExecutionModeDefaultSelect from '@/components/settings/ExecutionModeDefaultSelect.vue'
import AgentTimingSettings from '@/components/settings/AgentTimingSettings.vue'
import OrchestrationToggles from '@/components/templates/OrchestrationToggles.vue'
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

.behaviour-card {
  background: $elevation-raised;
}
</style>
