<template>
  <BaseDialog
    v-model="isOpen"
    :title="dialogTitle"
    :size="800"
    scrollable
    @cancel="handleClose"
  >
    <template #headerIcon>
      <div
        v-if="!isOrchestrator"
        class="agent-badge-sq"
        :style="{
          background: hexToRgba(getAgentDisplayNameColor(agent), 0.15),
          color: getAgentDisplayNameColor(agent),
        }"
      >{{ getAgentInitials(agent?.agent_display_name) }}</div>
      <v-icon v-else class="dlg-icon">mdi-information-outline</v-icon>
    </template>

    <template v-if="agent">
      <div v-if="!isOrchestrator" class="mb-4">
        <div class="d-flex align-center gap-2 mb-2">
          <span
            class="agent-tinted-badge"
            :style="{
              backgroundColor: hexToRgba(getAgentDisplayNameColor(agent), 0.15),
              color: getAgentDisplayNameColor(agent),
            }"
          >
            {{ agent.agent_display_name }}
          </span>
          <span class="text-body-small text-muted-a11y">Agent ID: {{ agent.agent_id || agent.id || '—' }}</span>
        </div>
      </div>

      <div v-if="loading" class="text-center py-8">
        <v-progress-circular indeterminate color="primary"></v-progress-circular>
        <div class="text-body-medium text-muted-a11y mt-3">Loading...</div>
      </div>

      <div v-else-if="error" class="py-4">
        <v-alert type="error" variant="tonal" density="compact">
          <strong>Failed to load:</strong> {{ error }}
        </v-alert>
      </div>

      <div v-else-if="!isOrchestrator && previewContent">
        <v-card variant="flat" class="template-content-card smooth-border">
          <pre class="template-content">{{ previewContent }}</pre>
        </v-card>
      </div>

      <div v-else-if="isOrchestrator && orchestratorPrompt">
        <v-card variant="flat" class="template-content-card smooth-border">
          <pre class="template-content">{{ orchestratorPrompt }}</pre>
        </v-card>
      </div>

      <div v-else-if="!isOrchestrator && !previewContent && !loading">
        <v-alert type="info" variant="tonal" density="compact">
          No template information available for this agent.
        </v-alert>
      </div>
    </template>

    <v-alert v-else type="warning" variant="tonal" density="compact">
      No agent information available.
    </v-alert>

    <template #actions>
      <v-spacer />
      <v-btn variant="text" @click="handleClose">Close</v-btn>
    </template>
  </BaseDialog>
</template>

<script setup>
import { ref, computed, watch, getCurrentInstance } from 'vue'
import BaseDialog from '@/components/common/BaseDialog.vue'
import api from '@/services/api'
import { getAgentColor as getAgentColorConfig, getAgentColorKey, getAgentInitials } from '@/config/agentColors'
import { hexToRgba } from '@/utils/colorUtils'

const props = defineProps({
  modelValue: {
    type: Boolean,
    required: true,
  },
  agent: {
    type: Object,
    default: null,
  },
})

const emit = defineEmits(['update:modelValue'])

const instance = getCurrentInstance()
const apiClient = instance?.appContext.config.globalProperties.$api || api

const loading = ref(false)
const error = ref(null)
const previewContent = ref(null)
const orchestratorPrompt = ref(null)

const isOpen = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val),
})

const isOrchestrator = computed(() => {
  return props.agent?.agent_display_name === 'orchestrator'
})

const dialogTitle = computed(() => {
  return isOrchestrator.value
    ? 'System Orchestrator Prompt'
    : `Agent Details: ${props.agent?.agent_name || 'Unknown Agent'}`
})

const handleClose = () => {
  emit('update:modelValue', false)
}

const getAgentDisplayNameColor = (agentEntity) => {
  return getAgentColorConfig(getAgentColorKey(agentEntity)).hex
}

const fetchTemplateData = async () => {
  const hasTemplateId = !!props.agent?.template_id
  const displayName = props.agent?.agent_display_name
  const agentName = props.agent?.agent_name

  if (!hasTemplateId && !displayName && !agentName) {
    error.value = null
    return
  }

  loading.value = true
  error.value = null
  previewContent.value = null

  try {
    let templateId = null

    if (hasTemplateId) {
      templateId = props.agent.template_id
    } else {
      const response = await apiClient.templates.list({ is_active: true })
      const templates = Array.isArray(response.data) ? response.data : (response.data?.templates || [])

      const searchTerms = [displayName, agentName].filter(Boolean).map(s => s.toLowerCase())
      const match = templates.find(t => {
        const templateName = (t.name || '').toLowerCase()
        const templateRole = (t.role || '').toLowerCase()
        return searchTerms.some(term =>
          templateName === term ||
          templateRole === term ||
          templateName.includes(term) ||
          term.includes(templateName)
        )
      })

      if (match) {
        templateId = match.id
      }
    }

    if (templateId) {
      const previewResponse = await apiClient.templates.preview(templateId, {})
      previewContent.value = previewResponse.data.preview
    }
  } catch (err) {
    console.error('[AgentDetailsModal] Failed to fetch template:', err)
    error.value = err.response?.data?.detail || err.message || 'Failed to fetch template data'
  } finally {
    loading.value = false
  }
}

const fetchOrchestratorPrompt = async () => {
  loading.value = true
  error.value = null
  orchestratorPrompt.value = null

  try {
    const response = await apiClient.system.getOrchestratorPrompt()
    orchestratorPrompt.value = response.data.content
  } catch (err) {
    console.error('[AgentDetailsModal] Failed to fetch orchestrator prompt:', err)
    error.value =
      err.response?.data?.detail || err.message || 'Failed to fetch orchestrator prompt'
  } finally {
    loading.value = false
  }
}

watch(
  () => props.modelValue,
  (newValue) => {
    if (newValue && props.agent) {
      previewContent.value = null
      orchestratorPrompt.value = null
      error.value = null

      if (isOrchestrator.value) {
        fetchOrchestratorPrompt()
      } else {
        fetchTemplateData()
      }
    }
  },
  { immediate: true }
)
</script>

<style lang="scss" scoped>
.template-content-card {
  max-height: 500px;
  overflow-y: auto;
  background-color: rgb(var(--v-theme-surface-variant));
}

.gap-2 {
  gap: 8px;
}
</style>
