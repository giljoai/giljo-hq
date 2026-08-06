<template>
  <v-container>
    <!-- Setup Banner (shown when database not configured) -->
    <AppAlert
      v-if="setupStatus.requires_setup"
      type="warning"
      prominent
      closable
      class="mb-4"
      @click:close="dismissSetupBanner"
    >
      <template v-slot:title>
        <v-icon left>mdi-database-alert</v-icon>
        Database Setup Required
      </template>
      <div>
        The database is not configured. Please complete the setup process to use all features.
      </div>
      <v-btn color="white" variant="outlined" class="mt-3" @click="navigateToSetup">
        <v-icon left>mdi-cog</v-icon>
        Go to Setup Wizard
      </v-btn>
    </AppAlert>

    <!-- LAN Setup Complete Banner -->
    <AppAlert
      v-if="showLanWelcome"
      type="success"
      prominent
      closable
      class="mb-4"
      @click:close="dismissLanWelcome"
    >
      <template v-slot:title>
        <v-icon left>mdi-check-circle</v-icon>
        Application Now Configured for LAN Access
      </template>
      <div class="mb-3">
        <p class="mb-2">
          <strong>Congratulations!</strong> {{ PRODUCT_NAME }} is now accessible over your local network.
        </p>
        <p class="mb-2">
          <strong>Server URL:</strong> <code>{{ serverProtocol }}://{{ serverIp }}:{{ serverPort }}</code>
        </p>
        <p class="text-body-medium">
          Download the comprehensive setup and testing guide to verify network connectivity and
          troubleshoot any issues.
        </p>
      </div>
      <v-btn color="white" variant="outlined" @click="downloadLanGuide">
        <v-icon left>mdi-download</v-icon>
        Download LAN Setup & Testing Guide
      </v-btn>
    </AppAlert>

    <!-- Header -->
    <div class="dash-header main-window-reveal main-window-reveal--hero main-window-delay-1">
      <h1 class="text-headline-large">Dashboard</h1>
    </div>

    <!-- Product Filter Pills (centered, scrollable) -->
    <div v-if="products.length > 1" class="product-filter-row main-window-reveal main-window-delay-2">
      <button
        class="product-filter-chevron"
        :class="{ 'product-filter-chevron--hidden': !canScrollLeft }"
        aria-label="Scroll filters left"
        @click="scrollFilterLeft"
      >
        <v-icon size="18">mdi-chevron-left</v-icon>
      </button>
      <div ref="filterScrollContainer" class="product-filter-scroll" @scroll="updateScrollState">
        <button
          class="pill-toggle smooth-border"
          :class="{ 'pill-toggle--active': selectedProductId === null }"
          @click="selectedProductId = null"
        >
          All
        </button>
        <button
          v-for="p in products"
          :key="p.id"
          class="pill-toggle smooth-border"
          :class="{ 'pill-toggle--active': selectedProductId === p.id }"
          @click="selectedProductId = p.id"
        >
          {{ p.name }}
        </button>
      </div>
      <button
        class="product-filter-chevron"
        :class="{ 'product-filter-chevron--hidden': !canScrollRight }"
        aria-label="Scroll filters right"
        @click="scrollFilterRight"
      >
        <v-icon size="18">mdi-chevron-right</v-icon>
      </button>
    </div>

    <!-- Stat Pills Row (3 cards: status, taxonomy, agent roles) -->
    <div class="stat-pills">
      <div class="stat-pill smooth-border main-window-reveal main-window-delay-3">
        <div class="stat-pill-label">Status Distribution</div>
        <div class="stat-pill-value">{{ statusPill.total }}<small>projects</small></div>
        <div class="micro-bar">
          <div
            v-for="seg in statusPill.segments"
            :key="seg.label"
            class="micro-seg"
            :style="{ width: seg.pct + '%', background: seg.color }"
          />
        </div>
        <div class="micro-legend">
          <div v-for="seg in statusPill.segments" :key="seg.label" class="micro-legend-item">
            <div class="micro-legend-dot" :style="{ background: seg.color }" />
            {{ seg.label }} {{ seg.count }}
          </div>
        </div>
      </div>

      <div class="stat-pill smooth-border main-window-reveal main-window-delay-4">
        <div class="stat-pill-label">Project Types</div>
        <div class="stat-pill-value">{{ taxonomyPill.total }}<small>types</small></div>
        <div class="micro-bar">
          <div
            v-for="seg in taxonomyPill.segments"
            :key="seg.label"
            class="micro-seg"
            :style="{ width: seg.pct + '%', background: seg.color }"
          />
        </div>
        <div class="micro-legend">
          <div v-for="seg in taxonomyPill.segments" :key="seg.label" class="micro-legend-item">
            <div class="micro-legend-dot" :style="{ background: seg.color }" />
            {{ seg.label }} {{ seg.count }}
          </div>
        </div>
      </div>

      <div class="stat-pill smooth-border main-window-reveal main-window-delay-5">
        <div class="stat-pill-label">Agent Roles</div>
        <div class="stat-pill-value">{{ agentRolePill.total }}<small>spawned</small></div>
        <div class="micro-bar">
          <div
            v-for="seg in agentRolePill.segments"
            :key="seg.label"
            class="micro-seg"
            :style="{ width: seg.pct + '%', background: seg.color }"
          />
        </div>
        <div class="micro-legend">
          <div v-for="seg in agentRolePill.segments" :key="seg.label" class="micro-legend-item">
            <div class="micro-legend-dot" :style="{ background: seg.color }" />
            {{ seg.label }} {{ seg.count }}
          </div>
        </div>
      </div>
    </div>

    <!-- Mini Stats Row (6 compact counters) -->
    <div class="mini-stats main-window-reveal main-window-delay-6">
      <div class="mini-stat smooth-border" style="--stat-accent: var(--agent-documenter-primary)">
        <div class="mini-stat-label">Active</div>
        <div class="mini-stat-value">{{ miniStats.active }}</div>
      </div>
      <div class="mini-stat smooth-border" style="--stat-accent: var(--agent-implementer-primary)">
        <div class="mini-stat-label">Tasks</div>
        <div class="mini-stat-value">{{ miniStats.tasks }}</div>
      </div>
      <div class="mini-stat smooth-border" style="--stat-accent: var(--agent-analyzer-primary)">
        <div class="mini-stat-label">API Calls</div>
        <div class="mini-stat-value">{{ miniStats.apiCalls }}</div>
      </div>
      <div class="mini-stat smooth-border" style="--stat-accent: var(--agent-reviewer-primary)">
        <div class="mini-stat-label">MCP Calls</div>
        <div class="mini-stat-value">{{ miniStats.mcpCalls }}</div>
      </div>
      <div class="mini-stat smooth-border" style="--stat-accent: var(--agent-tester-primary)">
        <div class="mini-stat-label">Commits</div>
        <div class="mini-stat-value">{{ miniStats.commits }}</div>
      </div>
    </div>

    <!-- Projects Panel (full width) -->
    <div class="panel projects-panel smooth-border main-window-reveal main-window-delay-7">
      <div class="panel-header">
        <span class="panel-title">Projects</span>
        <router-link to="/projects" class="panel-action">All Projects →</router-link>
      </div>
      <div class="panel-body">
        <RecentProjectsList :projects="dashboardData.recent_projects" @review-project="openProjectReview" />
      </div>
    </div>

    <!-- Bottom 2-column grid: 360 Memories + Git Commits -->
    <div class="bottom-grid">
      <div class="panel smooth-border main-window-reveal main-window-delay-8">
        <div class="panel-header">
          <span class="panel-title">360 Memories</span>
        </div>
        <div class="panel-body">
          <RecentMemoriesList :memories="dashboardData.recent_memories" @review-project="openProjectReview" />
        </div>
      </div>

      <div class="panel smooth-border main-window-reveal main-window-delay-9">
        <div class="panel-header">
          <span class="panel-title">Recent Commits</span>
          <span class="panel-subtitle">from 360 memory</span>
        </div>
        <div class="panel-body">
          <div v-if="recentCommits.length === 0" class="no-data-text">No commits captured in 360 memory yet</div>
          <div v-else>
            <div v-for="(c, i) in recentCommits" :key="i" class="commit-row">
              <span class="commit-sha">{{ c.sha?.substring(0, 8) }}</span>
              <div class="commit-content">
                <div class="commit-msg">{{ commitTitle(c) }}</div>
                <div class="commit-meta">
                  <span v-if="c.author">{{ c.author }}</span>
                  <span v-if="c.product_name"> · {{ c.product_name }}</span>
                  <span v-if="c.project_name"> · {{ c.project_name }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Project Review Modal (opened from Recently Completed Projects) -->
    <ProjectReviewModal
      :show="showReviewModal"
      :project-id="reviewProjectId"
      :product-id="reviewProductId"
      @close="showReviewModal = false; reviewProjectId = null; reviewProductId = null"
    />

  </v-container>
</template>

<script setup>
// eslint-allow giljo-internal/no-manual-api-url-composition (sanctioned: server-URL string is rendered for the user in a setup guide / inline UI, not used as the frontend HTTP client base — see ADR-001)
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { TEXT_MUTED_MATERIAL as COLOR_MUTED, COLOR_COMPLETE, COLOR_BRAND, COLOR_FAILED, COLOR_STAGED } from '@/config/colorTokens'
import { getAgentColor } from '@/config/agentColors'
import { commitTitle } from '@/utils/gitCommitDisplay'
import { PRODUCT_NAME } from '@/branding'
import AppAlert from '@/components/ui/AppAlert.vue'
import RecentProjectsList from '@/components/dashboard/RecentProjectsList.vue'
import RecentMemoriesList from '@/components/dashboard/RecentMemoriesList.vue'
import ProjectReviewModal from '@/components/projects/ProjectReviewModal.vue'
import { useRouter } from 'vue-router'
import { useProductStore } from '@/stores/products'
import api from '@/services/api'
import setupService from '@/services/setupService'
import { useToast } from '@/composables/useToast'

const router = useRouter()
const productStore = useProductStore()
const { showToast } = useToast()

// Product filter
const selectedProductId = ref(null)
const products = computed(() => productStore.products)
const filterScrollContainer = ref(null)
const canScrollLeft = ref(false)
const canScrollRight = ref(false)

function updateScrollState() {
  const el = filterScrollContainer.value
  if (!el) return
  canScrollLeft.value = el.scrollLeft > 0
  canScrollRight.value = el.scrollLeft + el.clientWidth < el.scrollWidth - 1
}

function scrollFilterLeft() {
  filterScrollContainer.value?.scrollBy({ left: -200, behavior: 'smooth' })
}

function scrollFilterRight() {
  filterScrollContainer.value?.scrollBy({ left: 200, behavior: 'smooth' })
}

// Reactive data
const setupStatus = ref({
  setup_mode: false,
  setup_complete: true,
  database_configured: true,
  database_connected: true,
  requires_setup: false,
})
const showLanWelcome = ref(false)
const serverIp = ref('localhost')
const serverPort = ref(parseInt(window.location.port) || 7272)
const serverProtocol = computed(() => window.location.protocol === 'https:' ? 'https' : 'http')

// Clock
const currentTime = ref('')
let clockInterval = null

function updateClock() {
  const now = new Date()
  const pad = n => String(n).padStart(2, '0')
  currentTime.value = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}`
}

// Project Review Modal
const showReviewModal = ref(false)
const reviewProjectId = ref(null)
const reviewProductId = ref(null)

function openProjectReview(item) {
  reviewProjectId.value = item.id || item.project_id
  reviewProductId.value = item.product_id || null
  if (reviewProjectId.value) showReviewModal.value = true
}

// Dashboard data from consolidated endpoint
const dashboardData = ref({
  project_status_dist: {},
  taxonomy_dist: [],
  agent_role_dist: [],
  recent_projects: [],
  recent_memories: [],
  task_status_dist: {},
  total_commits: 0,
})

// Server stats (always global)
const apiCallCount = ref(0)
const mcpCallCount = ref(0)
const recentCommits = ref([])

const statusColors = {
  active: getAgentColor('implementer').hex, // FE-2004: implementer blue, not COLOR_SURFACE (#fff = unreadable)
  inactive: COLOR_MUTED,
  completed: COLOR_COMPLETE,
  cancelled: COLOR_BRAND,
  terminated: COLOR_FAILED,
  staged: COLOR_STAGED,
}

// Helper: build segments array from data
function buildSegments(entries, total) {
  if (total === 0) return []
  return entries
    .filter(e => e.count > 0)
    .sort((a, b) => b.count - a.count)
    .map(e => ({
      label: e.label,
      count: e.count,
      color: e.color,
      pct: Math.max(1, Math.round((e.count / total) * 100)),
    }))
}

// Stat pill computeds
const statusPill = computed(() => {
  const dist = dashboardData.value.project_status_dist || {}
  const entries = []
  for (const [status, count] of Object.entries(dist)) {
    if (status === 'deleted') continue
    entries.push({
      label: status.charAt(0).toUpperCase() + status.slice(1),
      count,
      color: statusColors[status] || COLOR_MUTED,
    })
  }
  const total = entries.reduce((a, e) => a + e.count, 0)
  return { total, segments: buildSegments(entries, total) }
})

const taxonomyPill = computed(() => {
  const dist = dashboardData.value.taxonomy_dist || []
  const entries = dist.map(item => ({
    label: item.label || 'Untyped',
    count: item.count || 0,
    color: item.color || COLOR_MUTED,
  }))
  const total = entries.reduce((a, e) => a + e.count, 0)
  return { total, segments: buildSegments(entries, total) }
})

const agentRolePill = computed(() => {
  const dist = dashboardData.value.agent_role_dist || []
  const entries = dist.map(item => ({
    label: item.label || 'Unknown',
    count: item.count || 0,
    // Use the standardized code palette (implementer=blue, documenter=green, …)
    // keyed by role label rather than the DB background_color, so the bar always
    // matches the agent color coding used everywhere else. getAgentColor folds
    // variants (e.g. "implementer-backend") onto their base role.
    color: getAgentColor(item.label).hex,
  }))
  const total = entries.reduce((a, e) => a + e.count, 0)
  return { total, segments: buildSegments(entries, total) }
})

// Mini stats
const miniStats = computed(() => {
  const dist = dashboardData.value.project_status_dist || {}
  const taskDist = dashboardData.value.task_status_dist || {}
  const totalTasks = Object.values(taskDist).reduce((a, b) => a + b, 0)
  return {
    active: dist.active || 0,
    tasks: totalTasks,
    apiCalls: apiCallCount.value,
    mcpCalls: mcpCallCount.value,
    // BE-6078: true cumulative commit count from the dashboard stats payload,
    // NOT recentCommits.length (which was capped at the 10-item preview).
    commits: dashboardData.value.total_commits || 0,
  }
})

// Data fetching
const fetchDashboardData = async () => {
  try {
    const response = await api.stats.getDashboard(selectedProductId.value)
    if (response.data) {
      dashboardData.value = {
        project_status_dist: response.data.project_status_dist || {},
        taxonomy_dist: response.data.taxonomy_dist || [],
        agent_role_dist: response.data.agent_role_dist || [],
        recent_projects: response.data.recent_projects || [],
        recent_memories: response.data.recent_memories || [],
        task_status_dist: response.data.task_status_dist || {},
        total_commits: response.data.total_commits || 0,
      }
      // Extract git commits from 360 memory entries, preserving product/project context
      const commits = []
      for (const mem of (response.data.recent_memories || [])) {
        if (mem.git_commits && Array.isArray(mem.git_commits)) {
          for (const c of mem.git_commits) {
            commits.push({
              ...c,
              product_name: mem.product_name || null,
              project_name: mem.project_name || null,
            })
          }
        }
      }
      recentCommits.value = commits.slice(0, 10)
    }
  } catch (error) {
    console.error('Failed to fetch dashboard data:', error)
    showToast({ message: 'Unable to load dashboard data. Try refreshing the page.', type: 'error' })
  }
}

const fetchCallCounts = async () => {
  try {
    const response = await api.stats.getCallCounts()
    if (response.data) {
      apiCallCount.value = response.data.total_api_calls
      mcpCallCount.value = response.data.total_mcp_calls
    }
  } catch (error) {
    console.error('Failed to fetch call counts:', error)
    showToast({ message: 'Unable to load activity counts.', type: 'error' })
  }
}

// Re-fetch dashboard when product filter changes
watch(selectedProductId, () => fetchDashboardData())

// Poll cadence for live counters (Agent Roles, API Calls, MCP Calls).
// 60s is plenty; the WebSocket broker pushes events for everything else.
// FE-6059: raised 30s->60s and paused while the tab is hidden (Page Visibility
// API) so a backgrounded dashboard stops hammering /api/v1/stats/*.
const POLL_INTERVAL_MS = 60_000
let fetchInterval = null

function startPolling() {
  stopPolling()
  fetchInterval = setInterval(() => {
    fetchCallCounts()
  }, POLL_INTERVAL_MS)
}

function stopPolling() {
  if (fetchInterval) {
    clearInterval(fetchInterval)
    fetchInterval = null
  }
}

// Pause polling when the tab is backgrounded; resume + refetch immediately on
// re-show so the counters are current the moment the user looks again.
function handleVisibilityChange() {
  if (document.hidden) {
    stopPolling()
  } else {
    fetchCallCounts()
    startPolling()
  }
}

const checkSetupStatus = async () => {
  try {
    const status = await setupService.checkStatus()
    setupStatus.value = status
  } catch (error) {
    console.error('Failed to check setup status:', error)
    showToast({ message: 'Unable to check setup status.', type: 'warning' })
    setupStatus.value.requires_setup = false
  }
}

const dismissSetupBanner = () => {
  setupStatus.value.requires_setup = false
}

const navigateToSetup = () => {
  router.push('/setup/database')
}

// LAN Welcome Banner
const dismissLanWelcome = () => {
  showLanWelcome.value = false
  localStorage.removeItem('giljo_lan_setup_complete')
}

const downloadLanGuide = () => {
  const guideContent = generateLanGuide()
  const blob = new Blob([guideContent], { type: 'text/markdown' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = 'LAN_SETUP_GUIDE.md'
  link.click()
  URL.revokeObjectURL(url)
}

const generateLanGuide = () => {
  return `# ${PRODUCT_NAME} - LAN/Server Mode Setup Guide

**Network Configuration Complete**

This guide helps you verify and troubleshoot network connectivity for ${PRODUCT_NAME} in Server/LAN mode.

---

## Your Configuration

**Server URL:** ${serverProtocol.value}://${serverIp.value}:${serverPort.value}
**Mode:** Server/LAN
**Status:** Services restarted and ready

---

## Quick Network Tests

### From Another Device on Your Network:

**1. Ping Test (Basic Connectivity)**
\`\`\`bash
ping ${serverIp.value}
\`\`\`
Expected: Reply from ${serverIp.value}

**2. API Health Check**
\`\`\`bash
curl ${serverProtocol.value}://${serverIp.value}:${serverPort.value}/health
\`\`\`
Expected: {"status": "ok"}

**3. Browser Access**
Open: ${serverProtocol.value}://${serverIp.value}:${serverPort.value}

---

## Troubleshooting

**If ping works but API doesn't:**
- Verify firewall allows port ${serverPort.value}
- Check API server is running
- Confirm services restarted after configuration

**If nothing works:**
- Both devices must be on same network
- Check router's AP Isolation is disabled
- Verify firewall on both server and client

---

For complete troubleshooting guide, see: docs/LAN_SETUP_GUIDE.md

**Generated:** ${new Date().toLocaleString()}
`
}

// Lifecycle
onMounted(async () => {
  updateClock()
  clockInterval = setInterval(updateClock, 60000)
  // Initialize scroll chevron state after DOM renders
  setTimeout(updateScrollState, 100)

  // Check for LAN setup completion flag
  const lanSetupComplete = localStorage.getItem('giljo_lan_setup_complete')
  if (lanSetupComplete === 'true') {
    showLanWelcome.value = true

    try {
      const response = await fetch(`${setupService.baseURL}/api/v1/config`)
      if (response.ok) {
        const config = await response.json()
        if (config.server?.ip) {
          serverIp.value = config.server.ip
        }
        if (config.services?.api?.port) {
          serverPort.value = config.services.api.port
        }
      }
    } catch (error) {
      console.warn('[DASHBOARD] Could not fetch server config:', error)
    }
  }

  await checkSetupStatus()

  if (!setupStatus.value.requires_setup) {
    await Promise.all([
      fetchDashboardData(),
      fetchCallCounts(),
    ])
  }

  // Set up periodic refresh for live counters, paused while the tab is hidden.
  startPolling()
  document.addEventListener('visibilitychange', handleVisibilityChange)
})

onUnmounted(() => {
  stopPolling()
  document.removeEventListener('visibilitychange', handleVisibilityChange)
  if (clockInterval) {
    clearInterval(clockInterval)
  }
})
</script>

<style scoped lang="scss">
@use '../styles/variables' as *;
@use '../styles/design-tokens' as *;

/* ═══ HEADER ═══ */
.dash-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}

/* ═══ PRODUCT FILTER PILLS ═══ */
.product-filter-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  margin-bottom: 20px;
}

.product-filter-scroll {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  scroll-behavior: smooth;
  scrollbar-width: none;
  -ms-overflow-style: none;
  padding: 4px 0;
}

.product-filter-scroll::-webkit-scrollbar {
  display: none;
}

.product-filter-chevron {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  // FE-9365a: buttons are rounded squares — see main.scss Button Shape Standard.
  border-radius: 8px;
  border: none;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  flex-shrink: 0;
  transition: color 0.2s, background 0.2s;
}

.product-filter-chevron:hover {
  color: $color-brand-yellow;
  background: rgba($color-brand-yellow, 0.08);
}

.product-filter-chevron--hidden {
  opacity: 0;
  pointer-events: none;
}

.product-filter-row .pill-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border-radius: $border-radius-pill;
  padding: 6px 16px;
  font-size: 0.78rem;
  font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  transition: background 0.2s, color 0.2s, box-shadow 0.2s;
  background: transparent;
  color: var(--text-muted);
  border: none;
  white-space: nowrap;
  --smooth-border-color: #{$color-pill-border};
}

.product-filter-row .pill-toggle:hover {
  color: $color-text-hover;
}

.product-filter-row .pill-toggle--active,
.product-filter-row .pill-toggle--active:hover {
  background: rgba($color-brand-yellow, 0.12);
  color: $color-brand-yellow;
  box-shadow: none;
}

.dash-time {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.75rem;
  color: var(--text-muted);
}

/* ═══ STAT PILLS + MICRO-BARS ═══ */
.stat-pills {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
  margin-bottom: 24px;
}

.stat-pill {
  background: $elevation-raised;
  border-radius: $border-radius-rounded;
  padding: 14px 16px;
  transition: transform $transition-normal, box-shadow $transition-normal;

  &:hover {
    transform: translateY(-2px);
  }
}

.stat-pill-label {
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-muted);
  margin-bottom: 4px;
}

.stat-pill-value {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 1.4rem;
  font-weight: 500;
  margin-bottom: 10px;
  line-height: 1;
  color: $color-text-primary;

  small {
    font-size: 0.7rem;
    color: var(--text-muted);
    font-weight: 400;
    margin-left: 4px;
  }
}

.micro-bar {
  display: flex;
  height: 6px;
  border-radius: $border-radius-sharp;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.04);
  margin-bottom: 10px;
}

.micro-seg {
  height: 100%;
  transition: width 0.8s ease-out;

  & + & {
    margin-left: 1px;
  }
}

.micro-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 3px 12px;
}

.micro-legend-item {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 0.6rem;
  color: var(--text-secondary);
}

.micro-legend-dot {
  width: 5px;
  height: 5px;
  border-radius: $border-radius-sharp;
  flex-shrink: 0;
}

/* ═══ MINI STATS ROW ═══ */
.mini-stats {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px;
  margin-bottom: 24px;
}

.mini-stat {
  background: $elevation-raised;
  border-radius: $border-radius-default;
  padding: 12px 14px;
  position: relative;
  overflow: hidden;

  &::after {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 2px;
    background: var(--stat-accent, $color-border-secondary);
    opacity: 0.5;
  }
}

.mini-stat-label {
  font-size: 0.58rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-muted);
  margin-bottom: 2px;
  text-align: center;
}

.mini-stat-value {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 1.1rem;
  font-weight: 500;
  color: $color-text-primary;
  text-align: center;
}

/* ═══ PANEL PATTERN ═══ */
.panel {
  background: $elevation-raised;
  border-radius: $border-radius-rounded;
  overflow: hidden;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px;
  border-bottom: 1px solid $color-border-tertiary;
}

.panel-title {
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-secondary);
  font-weight: 500;
}

.panel-subtitle {
  font-size: 0.62rem;
  color: var(--text-muted);
  font-family: 'IBM Plex Mono', monospace;
}

.panel-action {
  font-size: 0.68rem;
  color: $color-brand-yellow;
  cursor: pointer;
  font-weight: 500;
  opacity: 0.7;
  text-decoration: none;

  &:hover {
    opacity: 1;
  }
}

.panel-body {
  padding: 14px 18px;
}

/* Projects panel — full width with bottom margin */
.projects-panel {
  margin-bottom: 20px;
}

/* ═══ BOTTOM GRID ═══ */
.bottom-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  align-items: stretch;
}

/* WI-3: Both bottom-grid panels share the same height; content scrolls if needed */
.bottom-grid > .panel {
  display: flex;
  flex-direction: column;
  max-height: 440px;
}

.bottom-grid > .panel > .panel-body {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}

/* ═══ COMMIT ROWS ═══ */
.commit-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 9px 0;
  border-bottom: 1px solid $color-border-tertiary;

  &:last-child {
    border-bottom: none;
  }
}

.commit-sha {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.62rem;
  color: $color-brand-yellow;
  flex-shrink: 0;
  opacity: 0.8;
}

.commit-content {
  min-width: 0;
}

.commit-msg {
  font-size: 0.75rem;
  line-height: 1.3;
  color: $color-text-primary;
}

.commit-meta {
  font-size: 0.58rem;
  color: var(--text-muted);
  margin-top: 1px;
}

.no-data-text {
  font-size: 0.75rem;
  color: var(--text-muted);
  padding: 8px 0;
}

/* ═══ RESPONSIVE ═══ */
@media (max-width: 1100px) {
  .mini-stats {
    grid-template-columns: repeat(3, 1fr);
  }

  .bottom-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 960px) {
  .stat-pills {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 600px) {
  .mini-stats {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
