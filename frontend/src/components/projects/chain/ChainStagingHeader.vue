<template>
  <div v-if="chainCtx" class="chain-staging-header">
    <ChainMissionWindow :mission="chainCtx.chainMission || chainCtx.headMission" />
    <ChainConductorCard
      v-if="chainCtx.conductorAgent"
      :conductor="chainCtx.conductorAgent"
      :label="chainCtx.conductor?.label || 'Conductor'"
    />
  </div>
</template>

<script setup>
import ChainMissionWindow from './ChainMissionWindow.vue'
import ChainConductorCard from './ChainConductorCard.vue'

defineProps({
  chainCtx: {
    type: Object,
    default: null,
  },
})
</script>
