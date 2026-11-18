<template>
  <div class="welcome-wrapper">
    <div class="welcome-atmosphere"></div>
    <div class="welcome-page">

      <div class="hero">
        <div class="hero-mascot">
          <div class="hero-mascot-glow"></div>
          <div class="hero-mascot-inner">
            <GilMascot :size="88" :dark-eyes="false" />
          </div>
        </div>
        <h1 class="hero-greeting">{{ fullGreeting }}</h1>
        <p class="hero-subtitle">
          The context engineering platform for AI-assisted development.<br>
          <span class="hero-subtitle-dim">Define your product once — every agent starts with the full picture.</span>
        </p>
      </div>

      <IntroVideoHomeCard />

      <div class="section-label">Quick Launch</div>
      <WelcomeQuickGrid
        :cards="quickCards"
        @card-click="onCardClick"
      />

      <WelcomeTeamSection
        v-if="onboardingComplete"
        :active-templates="activeTemplates"
        :empty-slots="emptySlots"
        :total-slots="totalSlots"
        :has-product="hasAnyProduct"
      />

      <div v-if="onboardingComplete && recentProjects.length > 0" class="recent-projects-section">
        <div class="recent-projects-panel smooth-border">
          <div class="rp-header">
            <span class="rp-title">Recent Projects</span>
            <router-link to="/Projects" class="rp-link">All Projects →</router-link>
          </div>
          <RecentProjectsList
            :projects="recentProjects"
            @review-project="handleReviewProject"
          />
        </div>
      </div>

      <div class="page-footer">
        <span class="footer-item mono">{{ appVersion }}</span>
      </div>
    </div>

    <ProjectReviewModal
      :show="showReviewModal"
      :project-id="reviewProjectId"
      :product-id="reviewProductId"
      @close="showReviewModal = false; reviewProjectId = null; reviewProductId = null"
    />

    <SetupWizardOverlay
      :model-value="showSetupOverlay && setupOverlayMode === 'setup'"
      :current-step="setupStep"
      :selected-tools="setupSelectedTools"
      :fresh="freshSetup"
      @update:model-value="showSetupOverlay = $event"
      @update:current-step="setupStep = $event"
      @step-complete="handleStepComplete"
      @dismiss="handleWizardDismiss"
    />
    <TutorialOverlay
      :model-value="showSetupOverlay && setupOverlayMode === 'learning'"
      :start-over="startTourOver"
      @update:model-value="showSetupOverlay = $event"
      @dismiss="handleTourDismiss"
    />
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { useProductStore } from '@/stores/products'
import { useProjectStore } from '@/stores/projects'
import { getAgentColor } from '@/config/agentColors'
import { templateRowActive } from '@/components/templates/templateTableConfig'
import api from '@/services/api'
import { PRODUCT_NAME } from '@/branding'
import { sortByRegistry } from '@/config/setupTools'
import GilMascot from '@/components/GilMascot.vue'
import SetupWizardOverlay from '@/components/setup/SetupWizardOverlay.vue'
import TutorialOverlay from '@/components/tutorial/TutorialOverlay.vue'
import RecentProjectsList from '@/components/dashboard/RecentProjectsList.vue'
import ProjectReviewModal from '@/components/projects/ProjectReviewModal.vue'
import configService from '@/services/configService'
import { PROJECT_TEMPLATES } from '@/composables/projectTemplates'
import { useStarterProject } from '@/composables/useStarterProject'
import { useDeferredHomeData } from '@/composables/useDeferredHomeData'
import { useWelcomeGreeting } from '@/composables/useWelcomeGreeting'
import WelcomeQuickGrid from './welcome/WelcomeQuickGrid.vue'
import WelcomeTeamSection from './welcome/WelcomeTeamSection.vue'
import IntroVideoHomeCard from '@/components/onboarding/IntroVideoHomeCard.vue'
import { useGuideStore } from '@/stores/guide'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const productStore = useProductStore()
const projectStore = useProjectStore()
const { busyTemplateId, createFromTemplate } = useStarterProject()
const guide = useGuideStore()

const showSetupOverlay = ref(false)
const setupStep = ref(0)
const forceSetupMode = ref(false)
const freshSetup = ref(false)
const startTourOver = ref(false)
const tourRequested = ref(false)

const setupComplete = computed(() => userStore.currentUser?.setup_complete ?? false)
const learningComplete = computed(() => userStore.currentUser?.learning_complete ?? false)
const setupOverlayMode = computed(() => {
  if (forceSetupMode.value) return 'setup'
  return tourRequested.value ? 'learning' : 'setup'
})

const setupStepCompleted = computed(() => userStore.currentUser?.setup_step_completed ?? 0)
const setupSelectedTools = computed(() => userStore.currentUser?.setup_selected_tools ?? [])

async function handleStepComplete({ step, data }) {
  if (step === 0 && data.tools) {
    const tools = freshSetup.value
      ? sortByRegistry([...new Set([...setupSelectedTools.value, ...data.tools])])
      : data.tools
    await userStore.updateSetupState({
      setup_selected_tools: tools,
      setup_step_completed: 1,
    })
  } else if (step === 1) {
    await userStore.updateSetupState({
      setup_step_completed: 2,
    })
  } else if (step === 2) {
    await userStore.updateSetupState({
      setup_step_completed: 3,
    })
  }
}

async function handleTourDismiss() {
  showSetupOverlay.value = false
  forceSetupMode.value = false
  tourRequested.value = false
  startTourOver.value = false

  if (!learningComplete.value) {
    await userStore.updateSetupState({ learning_complete: true })
  }
}

function handleWizardDismiss() {
  showSetupOverlay.value = false
  forceSetupMode.value = false
  freshSetup.value = false
}

function initialSetupStep() {
  if (!setupSelectedTools.value.length) return 0
  return Math.min(Math.max(Number(setupStepCompleted.value) || 0, 0), 1)
}

function openSetup() {
  freshSetup.value = false
  setupStep.value = initialSetupStep()
  showSetupOverlay.value = true
}

function revealSetup() {
  const ask = route.query.openSetup
  if (ask !== 'true' && ask !== 'new') return
  forceSetupMode.value = true
  freshSetup.value = ask === 'new'
  setupStep.value = freshSetup.value ? 0 : initialSetupStep()
  showSetupOverlay.value = true
  router.replace({ path: '/home' })
}
watch(() => route.query.openSetup, revealSetup)

watch(
  () => showSetupOverlay.value && setupOverlayMode.value === 'setup',
  (open) => {
    guide.setupWizardOpen = open
  },
  { immediate: true },
)
onBeforeUnmount(() => {
  guide.setupWizardOpen = false
})

const templates = ref([])
const totalSlots = ref(16)

const activeTemplates = computed(() =>
  templates.value
    .filter(t => templateRowActive(t))
    .map(t => {
      const color = getAgentColor(t.role || t.name)
      return {
        id: t.id,
        name: t.display_name || t.name,
        description: t.short_description || color.description,
        badge: color.badge,
        color: color.hex,
      }
    })
)

const emptySlots = computed(() => Math.max(0, totalSlots.value - activeTemplates.value.length - 1))

const hasActiveProduct = computed(() => !!productStore.activeProduct)
const hasAnyProduct = computed(() => productStore.hasProducts)
const activeProjectCount = computed(() => projectStore.activeProjects?.length ?? 0)
const hasAnyProject = computed(() => (projectStore.projects?.length ?? 0) > 0)

const setupCard = {
  title: 'Quick Setup',
  description: `Connect your AI coding tools and configure ${PRODUCT_NAME}.`,
  icon: 'mdi-rocket-launch',
  iconBg: 'rgba(255,195,0,0.1)',
  iconColor: 'var(--color-accent-primary)',
  accent: 'var(--color-accent-primary)',
  action: openSetup,
}

const dashboardCard = {
  title: 'Dashboard',
  description: 'View system stats, recent activity, and orchestration metrics at a glance.',
  icon: 'mdi-view-dashboard-outline',
  iconBg: 'rgba(109,179,228,0.12)',
  iconColor: getAgentColor('implementer').hex,
  accent: getAgentColor('implementer').hex,
  to: '/Dashboard',
}

const newProjectCard = computed(() => ({
  title: 'New Project',
  description: 'Create and launch a project with your Agent team or directly from your AI tool.',
  icon: 'mdi-plus-circle-outline',
  iconBg: 'rgba(255,195,0,0.1)',
  iconColor: 'var(--color-accent-primary)',
  accent: 'var(--color-accent-primary)',
  badge: '/giljo add project',
  to: '/Projects',
  attention: !hasAnyProject.value,
}))

const newProductCard = computed(() => ({
  title: 'New Product',
  description: 'Define a product to give your AI agents full context about what they\'re building.',
  icon: 'mdi-package-variant-closed',
  iconBg: 'rgba(255,195,0,0.1)',
  iconColor: 'var(--color-accent-primary)',
  accent: 'var(--color-accent-primary)',
  to: '/Products',
  attention: true,
}))

const activateProductCard = computed(() => ({
  title: 'Activate Product',
  description: 'You have a product but it\'s not active. Activate it to start creating projects.',
  icon: 'mdi-play-circle-outline',
  iconBg: 'rgba(255,195,0,0.1)',
  iconColor: 'var(--color-accent-primary)',
  accent: 'var(--color-accent-primary)',
  to: '/Products',
  attention: true,
}))

const taskBoardCard = {
  title: 'Task Board',
  description: 'Track technical debt, scope creep captures, and tasks or directly from your AI tool.',
  icon: 'mdi-clipboard-check-outline',
  iconBg: 'rgba(172,128,204,0.12)',
  iconColor: getAgentColor('reviewer').hex,
  accent: getAgentColor('reviewer').hex,
  badge: '/giljo add task',
  to: '/Tasks',
}

const lookupCard = {
  title: 'Look Up',
  description: 'Read projects and tasks from your AI tool — filter by status, type, or priority.',
  icon: 'mdi-magnify',
  iconBg: 'var(--agent-documenter-tinted)',
  iconColor: 'var(--agent-documenter-primary)',
  accent: 'var(--agent-documenter-primary)',
  badge: '/giljo',
  to: '/Tasks',
}

const activeProjectsCard = computed(() => ({
  title: 'Active Projects',
  description: 'Monitor running orchestrations, agent status, and real-time progress.',
  icon: 'mdi-play-circle-outline',
  iconBg: 'rgba(109,179,228,0.12)',
  iconColor: getAgentColor('implementer').hex,
  accent: getAgentColor('implementer').hex,
  badge: `${activeProjectCount.value} active`,
  to: '/jobs-overview',
}))

const templateCards = computed(() =>
  PROJECT_TEMPLATES.map((tmpl) => ({
    id: `template-${tmpl.id}`,
    templateId: tmpl.id,
    isTemplate: true,
    busy: busyTemplateId.value === tmpl.id,
    title: tmpl.cardTitle,
    description: tmpl.cardSubtitle,
    icon: tmpl.icon,
    iconBg: 'rgba(109,179,228,0.12)',
    iconColor: getAgentColor('implementer').hex,
    accent: getAgentColor('implementer').hex,
    action: () => createFromTemplate(tmpl),
  }))
)

function onCardClick(card) {
  if (card.busy) return
  if (typeof card.action === 'function') {
    card.action()
    return
  }
  if (card.to) {
    router.push(card.to)
  }
}

const onboardingComplete = computed(() => hasActiveProduct.value && hasAnyProject.value)

const quickCards = computed(() => {
  if (!setupComplete.value && !guide.visible) {
    return [setupCard]
  }
  if (!hasAnyProduct.value) {
    return [newProductCard.value]
  }
  if (!hasActiveProduct.value) {
    return [activateProductCard.value]
  }
  if (!hasAnyProject.value) {
    return [newProjectCard.value, ...templateCards.value]
  }
  if (activeProjectCount.value > 0) {
    return [activeProjectsCard.value, dashboardCard, taskBoardCard, lookupCard]
  }
  return [dashboardCard, newProjectCard.value, taskBoardCard, lookupCard]
})

const recentProjects = ref([])

function getUserDisplayName() {
  const user = userStore.currentUser
  return user?.first_name || user?.full_name || user?.username || user?.email?.split('@')[0] || 'Friend'
}

useDeferredHomeData({
  onboardingComplete,
  showIntegReminder: ref(false),
  templates,
  totalSlots,
  productId: computed(() => productStore.effectiveProductId || null),
})

const showReviewModal = ref(false)
const reviewProjectId = ref(null)
const reviewProductId = ref(null)

function handleReviewProject(project) {
  reviewProjectId.value = project.id || project.project_id
  reviewProductId.value = project.product_id || null
  if (reviewProjectId.value) showReviewModal.value = true
}

const appVersion = ref('')

const firstName = computed(() => {
  const name = getUserDisplayName()
  return String(name).split(' ')[0]
})
const { fullGreeting } = useWelcomeGreeting({ firstName })

onMounted(async () => {
  try {
    await configService.fetchConfig()
    appVersion.value = configService.getVersion()
  } catch { /* config may fail on first load */ }

  if (route.query.openGuide === 'true') {
    startTourOver.value = true
    tourRequested.value = true
    showSetupOverlay.value = true
    router.replace({ path: '/home' })
  } else {
    revealSetup()
  }

  const productsLoaded = productStore.fetchProducts().catch(() => {})

  await Promise.allSettled([
    productsLoaded,
    projectStore.fetchProjects().catch(() => {}),
    productsLoaded.then(() => {
      if (setupComplete.value && productStore.effectiveProductId) {
        return api.stats
          .getDashboard(productStore.effectiveProductId)
          .then((response) => {
            recentProjects.value = response.data?.recent_projects || []
          })
          .catch(() => {})
      }
    }),
  ])
})
</script>

<style lang="scss" scoped>
@use '../styles/design-tokens' as *;
.welcome-wrapper {
  position: relative;
  min-height: 100%;
}

.welcome-atmosphere {
  position: fixed;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  background:
    radial-gradient(ellipse 700px 500px at 50% 15%, rgba(255,195,0,0.04) 0%, transparent 60%),
    radial-gradient(ellipse 500px 500px at 80% 60%, rgba(109,179,228,0.03) 0%, transparent 60%);
}

.welcome-page {
  position: relative;
  z-index: 1;
  max-width: 960px;
  margin: 0 auto;
  padding: 40px 32px 48px;
}

/* ═══ HERO ═══ */
.hero {
  text-align: center;
  margin-bottom: 36px;
  animation: fadeSlideDown 0.6s ease-out;
}

.hero-mascot {
  position: relative;
  display: inline-block;
  width: 88px;
  height: 100px;
  margin-bottom: 20px;
}

.hero-mascot-inner {
  position: relative;
  z-index: 1;
  filter: drop-shadow(0 0 14px rgba(255,195,0,0.35)) drop-shadow(0 0 36px rgba(107,207,127,0.15));
  animation: mascotFloat 4s ease-in-out infinite;
}

.hero-mascot-glow {
  position: absolute;
  inset: -20px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(255,217,61,0.14) 0%, rgba(107,207,127,0.06) 50%, transparent 70%);
  z-index: 0;
  animation: glowPulse 4s ease-in-out infinite;
}

.hero-greeting {
  font-size: 1.65rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  margin-bottom: 6px;
  color: var(--color-text-primary);
}

.hero-subtitle {
  font-size: 0.88rem;
  color: var(--text-secondary);
  font-weight: 300;
  max-width: 480px;
  margin: 0 auto;
  line-height: 1.55;
}

.hero-subtitle-dim {
  opacity: 0.7;
}

/* ═══ SECTION LABEL ═══ */
.section-label {
  font-size: 0.68rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--text-muted);
  margin-bottom: 12px;
  font-weight: 500;
}

/* ═══ RECENT PROJECTS ═══ */
.recent-projects-section {
  margin-bottom: 36px;
  animation: fadeSlideUp 0.45s ease-out 0.42s both;
}

.recent-projects-panel {
  background: rgb(var(--v-theme-surface));
  border-radius: $border-radius-rounded;
  overflow: hidden;
}

.rp-header {
  padding: 16px 20px;
  border-bottom: 1px solid rgba(255,255,255,0.04);
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.rp-title {
  font-size: 0.92rem;
  font-weight: 600;
}

.rp-link {
  font-size: 0.68rem;
  color: $yellow;
  cursor: pointer;
  font-weight: 500;
  opacity: 0.7;
  text-decoration: none;
}

.rp-link:hover {
  opacity: 1;
}

/* ═══ FOOTER ═══ */
.page-footer {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  padding-top: 20px;
  border-top: 1px solid rgba(255,255,255,0.04);
  animation: fadeSlideUp 0.45s ease-out 0.55s both;
}

.footer-item {
  font-size: 0.68rem;
  color: var(--text-muted);
}

.footer-item.mono {
  font-family: 'IBM Plex Mono', monospace;
}

/* ═══ ANIMATIONS ═══ */
@keyframes fadeSlideDown {
  from { opacity: 0; transform: translateY(-14px); }
  to { opacity: 1; transform: translateY(0); }
}

@keyframes fadeSlideUp {
  from { opacity: 0; transform: translateY(16px); }
  to { opacity: 1; transform: translateY(0); }
}

@keyframes mascotFloat {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-4px); }
}

@keyframes glowPulse {
  0%, 100% { opacity: 0.8; transform: scale(1); }
  50% { opacity: 1; transform: scale(1.06); }
}

/* ═══ RESPONSIVE ═══ */
@media (max-width: 960px) {
  .welcome-page {
    padding: 32px 20px 40px;
  }
}
</style>
