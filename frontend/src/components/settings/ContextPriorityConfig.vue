<template>
  <div>
    <div class="tab-header mb-4 d-flex justify-space-between align-center">
      <h2 class="text-title-large">Context Configuration</h2>
      <v-btn
        variant="text"
        size="small"
        :loading="saving"
        :disabled="saving || loading"
        @click="resetToDefaults"
        data-testid="reset-context-config-btn"
        class="reset-btn"
      >
        Reset
      </v-btn>
    </div>
    <v-card variant="flat" class="smooth-border context-card">
    <v-progress-linear v-if="loading || saving" indeterminate color="primary" height="2" />
    <v-card-text>
      <v-alert
        v-if="!props.gitIntegrationEnabled"
        type="info"
        variant="tonal"
        density="compact"
        class="mb-4"
      >
        <div>
          <strong>Git History is disabled</strong>
          <br />
          Git integration is currently disabled. Enable it in the
          <a
            @click="navigateToIntegrations"
            class="text-decoration-underline cursor-pointer"
          >
            Connect tab
          </a>
          to use Git History context.
        </div>
      </v-alert>

      <div class="mb-4">
        <div class="text-title-small font-weight-medium mb-2">Toggle Configuration (What to Fetch)</div>
        <v-alert type="info" variant="tonal" density="compact" class="mb-3">
          Toggle fields on/off to include or exclude from context.
        </v-alert>

        <div class="context-row locked-row d-flex justify-space-between align-center py-2">
          <div class="d-flex align-center flex-grow-1">
            <span class="text-body-medium context-label">Product Info</span>
            <v-tooltip text="Product Info is always included" location="bottom">
              <template #activator="{ props }">
                <v-icon v-bind="props" size="small" color="primary" class="ml-2">mdi-lock</v-icon>
              </template>
            </v-tooltip>
          </div>
          <v-chip size="small" color="primary" variant="flat" class="d-flex align-center justify-center always-on-chip">
            <span class="always-on-label">ALWAYS ON</span>
          </v-chip>
        </div>

        <div class="context-row locked-row d-flex justify-space-between align-center py-2">
          <div class="d-flex align-center flex-grow-1">
            <span class="text-body-medium context-label">Project Description</span>
            <v-tooltip text="Project Description is always included" location="bottom">
              <template #activator="{ props }">
                <v-icon v-bind="props" size="small" color="primary" class="ml-2">mdi-lock</v-icon>
              </template>
            </v-tooltip>
          </div>
          <v-chip size="small" color="primary" variant="flat" class="d-flex align-center justify-center always-on-chip">
            <span class="always-on-label">ALWAYS ON</span>
          </v-chip>
        </div>

        <div
          v-for="context in toggleOnlyContexts"
          :key="context.key"
          class="context-row d-flex justify-space-between align-center py-2"
        >
          <div class="d-flex align-center flex-grow-1">
            <span class="text-body-medium context-label">{{ context.label }}</span>
            <v-switch
              :model-value="config[context.key]?.enabled"
              @update:model-value="toggleContext(context.key)"
              hide-details
              color="primary"
              :aria-label="`Toggle ${context.label}`"
              class="ml-2"
            />
          </div>
        </div>
      </div>

      <v-divider class="my-4" />

      <div>
        <div class="text-title-small font-weight-medium mb-2">Depth Configuration (How Much Detail)</div>
        <v-alert type="info" variant="tonal" density="compact" class="mb-3">
          Control the level of detail for context fields with adjustable depth.
        </v-alert>

        <div
          v-for="context in depthControlledContexts"
          :key="context.key"
          class="context-row d-flex justify-space-between align-center py-2"
          :class="{ 'disabled-row': isContextDisabled(context.key) }"
        >
          <div class="d-flex align-center flex-grow-1">
            <span class="text-body-medium context-label">{{ context.label }}</span>
            <v-switch
              :model-value="config[context.key]?.enabled"
              @update:model-value="toggleContext(context.key)"
              hide-details
              color="primary"
              :aria-label="
                isContextDisabled(context.key)
                  ? `${context.label} disabled - Git integration required`
                  : `Toggle ${context.label}`
              "
              class="ml-2"
              :disabled="isContextDisabled(context.key)"
            />
            <v-tooltip
              v-if="context.helpText"
              :text="context.helpText"
              location="bottom"
            >
              <template #activator="{ props }">
                <v-icon v-bind="props" size="small" color="primary" class="ml-1">mdi-help-circle-outline</v-icon>
              </template>
            </v-tooltip>
          </div>

          <v-menu
            v-model="depthMenuOpen[context.key]"
            :close-on-content-click="true"
            location="bottom"
            offset="4"
            :disabled="!config[context.key]?.enabled || isContextDisabled(context.key)"
          >
            <template v-slot:activator="{ props: menuProps }">
              <v-chip
                v-bind="menuProps"
                color="grey-darken-1"
                variant="flat"
                size="small"
                class="depth-chip mx-2"
                :class="{ 'depth-chip-disabled': !config[context.key]?.enabled || isContextDisabled(context.key) }"
                :aria-label="`${context.label} depth setting`"
                :data-testid="`depth-${context.key.replace('_', '-')}`"
                role="button"
                tabindex="0"
              >
                <span class="pill-text">{{ getDepthLabel(context.key) }}</span>
                <v-icon size="x-small" class="ml-1">mdi-chevron-down</v-icon>
              </v-chip>
            </template>

            <v-list density="compact" class="depth-menu-list">
              <v-list-item
                v-for="option in formatOptions(context)"
                :key="option.value"
                :value="option.value"
                @click="updateDepth(context.key, option.value)"
                :class="{ 'v-list-item--active': getDepthValue(context.key) === option.value }"
              >
                <v-list-item-title class="font-weight-medium">{{ option.title }}</v-list-item-title>
                <v-list-item-subtitle v-if="option.subtitle" class="text-body-small">{{ option.subtitle }}</v-list-item-subtitle>
              </v-list-item>
            </v-list>
          </v-menu>
        </div>
      </div>
    </v-card-text>
  </v-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { apiClient } from '@/services/api'
import { useToast } from '@/composables/useToast'

const router = useRouter()
const { showToast } = useToast()

const props = defineProps({
  gitIntegrationEnabled: {
    type: Boolean,
    default: false,
  },
})

const contexts = [
  { key: 'tech_stack', label: 'Tech Stack' },
  { key: 'architecture', label: 'Architecture' },
  { key: 'testing', label: 'Testing' },
  {
    key: 'vision_documents',
    label: 'Vision Documents',
    helpText: '33% / 66% / 100% context-depth summaries populated by your AI tool during vision analysis'
  },
  {
    key: 'memory_360',
    label: '360 Memory',
    options: [1, 3, 5, 10],
    helpText: 'Number of previous project summaries to include'
  },
  {
    key: 'git_history',
    label: 'Git History',
    options: [5, 10, 25, 50, 100],
    helpText: 'Number of git commits in CLI examples'
  },
]

const UI_TO_BACKEND_CATEGORY_MAP: Record<string, string> = {
  tech_stack: 'tech_stack',
  architecture: 'architecture',
  testing: 'testing',
  vision_documents: 'vision_documents',
  memory_360: 'memory_360',
  git_history: 'git_history',
}

const BACKEND_TO_UI_CATEGORY_MAP: Record<string, string[]> = {
  tech_stack: ['tech_stack'],
  architecture: ['architecture'],
  testing: ['testing'],
  vision_documents: ['vision_documents'],
  memory_360: ['memory_360'],
  git_history: ['git_history'],
}

const depthMenuOpen = ref<Record<string, boolean>>({})

function getDepthLabel(key: string): string {
  const value = getDepthValue(key)
  if (key === 'memory_360') {
    return `${value} projects`
  } else if (key === 'git_history') {
    return `${value} commits`
  } else if (key === 'vision_documents') {
    const labels: Record<string, string> = { light: 'Light', medium: 'Medium', full: 'Full' }
    return labels[value as string] || 'Light'
  }
  return String(value)
}

interface ContextConfig {
  enabled: boolean
  depth?: string
  count?: number
}

const config = ref<Record<string, ContextConfig>>({
  tech_stack: { enabled: true },
  architecture: { enabled: true },
  testing: { enabled: true },
  vision_documents: { enabled: true, depth: 'medium' },
  memory_360: { enabled: true, count: 3 },
  git_history: { enabled: false, count: 25 },
  agent_templates: { enabled: true, depth: 'basic' },
})

const loading = ref(false)
const saving = ref(false)
const fetchingVisionStats = ref(false)
const visionStats = ref(null)
const configLoaded = ref(false)

const toggleOnlyContexts = computed(() => {
  return contexts.filter(c => !c.options && c.key !== 'vision_documents')
})

const depthControlledContexts = computed(() => {
  return contexts.filter(c => c.options || c.key === 'vision_documents')
})

function toggleContext(key: string) {
  config.value[key].enabled = !config.value[key].enabled
  saveConfig()
}

function updateDepth(key: string, value: string | number) {
  const contextDef = contexts.find((c) => c.key === key)
  if (!contextDef) return

  if (key === 'memory_360' || key === 'git_history') {
    config.value[key].count = value as number
  } else if (key === 'vision_documents' || key === 'agent_templates') {
    config.value[key].depth = value as string
  }
  saveConfig()
}

function getDepthValue(key: string): string | number | undefined {
  const contextConfig = config.value[key]
  if (!contextConfig) return undefined

  if (key === 'memory_360' || key === 'git_history') {
    return contextConfig.count
  } else if (key === 'vision_documents' || key === 'agent_templates') {
    return contextConfig.depth
  }
  return undefined
}

function formatOptions(context: { key: string; options?: (string | number)[] }) {
  if (context.key === 'vision_documents') {
    return [
      {
        title: 'Light (33% Summary)',
        value: 'light',
        subtitle: 'Compressed overview'
      },
      {
        title: 'Medium (66% Summary)',
        value: 'medium',
        subtitle: 'More detail, still compressed'
      },
      {
        title: 'Full (100% Complete)',
        value: 'full',
        subtitle: 'All content, paginated ≤25K/call'
      }
    ]
  }

  if (!context.options) return []

  return context.options.map((opt) => {
    if (typeof opt === 'number') {
      if (context.key === 'memory_360') {
        return { title: `${opt} project${opt === 1 ? '' : 's'}`, value: opt }
      } else if (context.key === 'git_history') {
        return { title: `${opt} commits`, value: opt }
      }
      return { title: String(opt), value: opt }
    }
    return { title: opt.charAt(0).toUpperCase() + opt.slice(1).replace('_', ' '), value: opt }
  })
}

function isContextDisabled(contextKey: string): boolean {
  return contextKey === 'git_history' && !props.gitIntegrationEnabled
}

function navigateToIntegrations() {
  router.push({ name: 'Tools', query: { tab: 'connect' } })
}

watch(() => props.gitIntegrationEnabled, (enabled, oldEnabled) => {
  if (!configLoaded.value) return
  if (enabled === oldEnabled) return

  if (!enabled && config.value.git_history?.enabled) {
    config.value.git_history.enabled = false
    saveConfig()
  } else if (enabled && !config.value.git_history?.enabled) {
    config.value.git_history.enabled = true
    config.value.git_history.count = config.value.git_history.count || 5
    saveConfig()
  }
})

async function fetchVisionStats() {
  fetchingVisionStats.value = true
  try {
    const response = await apiClient.get('/api/v1/products/active/vision-stats')
    visionStats.value = response.data
  } catch (error) {
    console.warn('[CONTEXT CONFIG] Failed to fetch vision stats:', error)
    visionStats.value = null
  } finally {
    fetchingVisionStats.value = false
  }
}

function formatTokenCount(tokens) {
  if (tokens >= 1000) {
    const k = (tokens / 1000).toFixed(1)
    return k + 'K'
  }
  return tokens.toString()
}

async function fetchConfig() {
  loading.value = true
  try {
    const toggleResponse = await apiClient.get('/api/v1/users/me/field-priority')
    const toggles = toggleResponse.data?.priorities || {}

    Object.entries(toggles).forEach(([backendKey, value]) => {
      const frontendKeys = BACKEND_TO_UI_CATEGORY_MAP[backendKey] || [backendKey]

      frontendKeys.forEach((frontendKey) => {
        if (config.value[frontendKey]) {
          let enabled: boolean
          if (typeof value === 'object' && value !== null && 'toggle' in value) {
            enabled = (value as { toggle: boolean }).toggle
          } else if (typeof value === 'boolean') {
            enabled = value
          } else if (typeof value === 'number') {
            enabled = (value as number) !== 4
          } else {
            enabled = true
          }

          config.value[frontendKey] = {
            ...config.value[frontendKey],
            enabled,
          }
        }
      })
    })

    try {
      const depthResponse = await apiClient.get('/api/v1/users/me/context/depth')
      const depthData = depthResponse.data?.depth_config || {}

      if (depthData.memory_last_n_projects && config.value.memory_360) {
        config.value.memory_360.count = depthData.memory_last_n_projects
      }
      if (depthData.git_commits && config.value.git_history) {
        config.value.git_history.count = depthData.git_commits
      }
      if (depthData.vision_documents && config.value.vision_documents) {
        config.value.vision_documents.depth = depthData.vision_documents
      }
      if (depthData.agent_templates && config.value.agent_templates) {
        config.value.agent_templates.depth = depthData.agent_templates
      }
    } catch (depthError) {
      console.warn('[CONTEXT CONFIG] Depth config not available, using defaults:', depthError)
    }

    configLoaded.value = true

    if (!props.gitIntegrationEnabled && config.value.git_history?.enabled) {
      config.value.git_history.enabled = false
      saveConfig()
    }
  } catch (error) {
    console.error('[CONTEXT CONFIG] Failed to fetch config:', error)
    configLoaded.value = true
  } finally {
    loading.value = false
  }
}

async function saveConfig() {
  saving.value = true
  try {
    await apiClient.put('/api/v1/users/me/field-priority', {
      version: '3.0',
      priorities: convertToBackendFormat(config.value),
    })

    try {
      await apiClient.put('/api/v1/users/me/context/depth', {
        depth_config: {
          memory_last_n_projects: config.value.memory_360?.count || 3,
          git_commits: config.value.git_history?.count || 25,
          vision_documents: config.value.vision_documents?.depth || 'light',
          agent_templates: config.value.agent_templates?.depth || 'basic',
        }
      })
    } catch (depthError) {
      console.error('[CONTEXT CONFIG] Depth config save failed:', depthError)
      showToast({ message: 'Depth settings failed to save. Please try again.', type: 'error' })
    }
  } catch (error) {
    console.error('[CONTEXT CONFIG] Failed to save config:', error)
  } finally {
    saving.value = false
  }
}

function resetToDefaults() {
  config.value = {
    tech_stack: { enabled: true },
    architecture: { enabled: true },
    testing: { enabled: true },
    vision_documents: { enabled: true, depth: 'medium' },
    memory_360: { enabled: true, count: 3 },
    git_history: { enabled: true, count: 25 },
    agent_templates: { enabled: true, depth: 'basic' },
  }

  if (!props.gitIntegrationEnabled) {
    config.value.git_history.enabled = false
  }

  saveConfig()
}

function convertToBackendFormat(localConfig: Record<string, ContextConfig>): Record<string, { toggle: boolean }> {
  const backendToggles: Record<string, { toggle: boolean }> = {}

  Object.entries(localConfig).forEach(([uiKey, value]) => {
    const backendKey = UI_TO_BACKEND_CATEGORY_MAP[uiKey] || uiKey
    backendToggles[backendKey] = { toggle: value.enabled }
  })

  return backendToggles
}

onMounted(async () => {
  fetchConfig()
  await fetchVisionStats()
})

defineExpose({
  contexts,
  toggleOnlyContexts,
  depthControlledContexts,
  config,
  loading,
  saving,
  fetchingVisionStats,
  visionStats,
  toggleContext,
  updateDepth,
  saveConfig,
  resetToDefaults,
  isContextDisabled,
  navigateToIntegrations,
  fetchVisionStats,
  formatTokenCount,
  getDepthLabel,
  depthMenuOpen,
})
</script>

<style lang="scss" scoped>
@use '../../styles/design-tokens' as *;
.context-card {
  background: $elevation-raised;
  border-radius: $border-radius-rounded;
}

.reset-btn {
  width: 140px;
}

.context-row {
  border-bottom: 1px solid rgba(var(--v-theme-on-surface), 0.08);
  min-height: 52px;
  padding-top: 12px;
  padding-bottom: 12px;
}

.context-row:last-of-type {
  border-bottom: none;
}

/* Make v-switch compact */
.context-row :deep(.v-switch) {
  margin: 0;
  flex: none;
}

.context-row :deep(.v-switch .v-selection-control) {
  min-height: auto;
}

.locked-row {
  background-color: rgba(var(--v-theme-primary), 0.05);
  border-radius: $border-radius-sharp;
  padding-left: 12px;
  padding-right: 12px;
}

.disabled-row {
  opacity: 0.5;
  pointer-events: none;
}

.context-label {
  min-width: 140px;
}

.always-on-chip {
  width: 140px;
  text-align: center;
}

.always-on-label {
  font-size: 0.75rem;
  font-weight: 600;
  line-height: 1;
  position: relative;
  top: 1px;
}

.pill-text {
  font-size: 0.75rem;
  font-weight: 600;
  line-height: 1;
}

/* Depth Pill Chip Styles */
.depth-chip {
  cursor: pointer;
  transition: all $transition-normal ease;
  user-select: none;
  width: 140px;
  text-align: center;
  display: flex;
  align-items: center;
  justify-content: center;
}

.depth-chip:not(.depth-chip-disabled):hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
}

.depth-chip:focus-visible {
  outline: 2px solid currentColor;
  outline-offset: 2px;
}

.depth-chip-disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Depth Menu List Styles */
.depth-menu-list {
  min-width: 280px;
}

.depth-menu-list .v-list-item {
  cursor: pointer;
  transition: background-color $transition-normal ease;
}

.depth-menu-list .v-list-item:hover {
  background-color: rgba(var(--v-theme-on-surface), 0.08);
}

.depth-menu-list .v-list-item:focus-visible {
  outline: 2px solid rgba(var(--v-theme-primary), 0.5);
  outline-offset: -2px;
}

.depth-menu-list .v-list-item--active {
  background-color: rgba(var(--v-theme-primary), 0.12);
}
</style>
