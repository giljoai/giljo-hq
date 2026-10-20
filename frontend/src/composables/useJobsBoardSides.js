
import { computed, nextTick, ref, watch } from 'vue'
import { useProjectStore } from '@/stores/projects'
import { useSequenceRunStore } from '@/stores/sequenceRunStore'
import { useProjectTabsStore } from '@/stores/projectTabs'
import { JOBS_SECTION_LABELS, withChainReview } from '@/utils/jobsSectionLabel'

const STAGING_SIDE_LABELS = new Set([
  JOBS_SECTION_LABELS.ACTIVATED,
  JOBS_SECTION_LABELS.PLANNING,
  JOBS_SECTION_LABELS.STAGED,
])
const CHAIN_IMPLEMENTATION_STATUSES = new Set(['running', 'stalled', 'completed', 'failed', 'terminated', 'cancelled'])

const STATUS_LINES = {
  staging: [
    { value: 'activated', label: 'Activated', section: JOBS_SECTION_LABELS.ACTIVATED },
    { value: 'planning', label: 'Planning', section: JOBS_SECTION_LABELS.PLANNING },
    { value: 'staged', label: 'Staged', section: JOBS_SECTION_LABELS.STAGED },
  ],
  implementation: [
    { value: 'needs-decision', label: 'Needs decision', section: JOBS_SECTION_LABELS.NEEDS_DECISION },
    { value: 'needs-attention', label: 'Needs attention', section: JOBS_SECTION_LABELS.NEEDS_ATTENTION },
    { value: 'implementing', label: 'Implementing', section: JOBS_SECTION_LABELS.IMPLEMENTING },
    { value: 'review', label: 'Review', section: JOBS_SECTION_LABELS.REVIEW },
  ],
}

export function useJobsBoardSides({
  route,
  router,
  projects,
  soloUnreviewed,
  chainRuns,
  runMembers,
  sectionLabelOf,
  board,
  openDetail,
  productGroups,
  groupFold,
  refresh,
}) {
  const projectStore = useProjectStore()
  const sequenceRunStore = useSequenceRunStore()

  function sideOf(project) {
    return STAGING_SIDE_LABELS.has(sectionLabelOf(project)) ? 'staging' : 'implementation'
  }
  function sideOfRun(run) {
    return CHAIN_IMPLEMENTATION_STATUSES.has(run?.status) ? 'implementation' : 'staging'
  }
  function sideHolding(project) {
    const run = chainRuns.value.find((r) => runMembers(r).includes(project.id))
    return run ? sideOfRun(run) : sideOf(project)
  }

  function cardsOnSide(which, { withDone = true } = {}) {
    const cards = new Map()
    projects.value.filter((project) => sideOf(project) === which).forEach((p) => cards.set(p.id, p))
    if (withDone && which === 'implementation') soloUnreviewed.value.forEach((p) => cards.set(p.id, p))
    for (const run of chainRuns.value.filter((r) => sideOfRun(r) === which)) {
      for (const id of runMembers(run)) {
        const member = projectStore.projectById(id)
        const needsReview = run.project_statuses?.[id] === 'completed' && !sequenceRunStore.isReviewed(run.id, id)
        cards.set(id, member ? withChainReview(member, needsReview) : null)
      }
    }
    return cards
  }
  const sideCounts = computed(() => ({
    staging: cardsOnSide('staging', { withDone: false }).size,
    implementation: cardsOnSide('implementation', { withDone: false }).size,
  }))

  const side = ref('implementation')
  function selectSide(value) {
    side.value = value
  }

  const sideProjects = computed(() => projects.value.filter((project) => sideOf(project) === side.value))
  const sideUnreviewed = computed(() => (side.value === 'implementation' ? soloUnreviewed.value : []))
  const sideChainRunIds = computed(() =>
    chainRuns.value.filter((run) => sideOfRun(run) === side.value).map((run) => run.id),
  )
  const countLine = computed(() => {
    if (side.value === 'staging') {
      return `${sideCounts.value.staging} waiting for a go · staged projects move to Implementation when you press Play`
    }
    const parts = [`${sideCounts.value.implementation} in flight`]
    if (soloUnreviewed.value.length) parts.push(`${soloUnreviewed.value.length} done, not reviewed`)
    return parts.join(' · ')
  })

  const visibleCards = computed(() => [...cardsOnSide(side.value).values()].filter(Boolean))
  const statusCounts = computed(() => {
    const sections = visibleCards.value.map(sectionLabelOf)
    return STATUS_LINES[side.value].map(({ value, label, section }) => ({
      value,
      label,
      count: sections.filter((s) => s === section).length,
    }))
  })

  const tabsStore = useProjectTabsStore()
  watch(
    () => (tabsStore.isLaunched ? tabsStore.currentProject : null),
    async (launched) => {
      if (!launched) return
      await refresh()
      selectSide('implementation')
    },
  )

  const arrivalProjectId = computed(() => (typeof route.query.project === 'string' ? route.query.project : null))
  const highlightedRunId = computed(() => (typeof route.query.run === 'string' ? route.query.run : null))

  async function consumeArrival() {
    if (!arrivalProjectId.value) return
    const project = projectStore.activeProjectsMeta.find((p) => p.id === arrivalProjectId.value)
    if (project) {
      board.focus(project)
      selectSide(sideHolding(project))
    }
    const rest = board.consumeArrival(route.query, project, { onDetail: openDetail })
    if (rest) router.replace({ query: rest })
    await nextTick()
    document.querySelector('[data-arrival="true"]')?.scrollIntoView?.({ block: 'start' })
  }

  async function revealHighlightedRun() {
    if (!highlightedRunId.value) return
    const run = chainRuns.value.find((r) => r.id === highlightedRunId.value)
    if (run) selectSide(sideOfRun(run))
    for (const group of productGroups()) {
      if (group.runIds.includes(highlightedRunId.value)) groupFold.unfold(group.id)
    }
    await nextTick()
    const group = [...document.querySelectorAll('[data-run-id]')].find(
      (el) => el.dataset.runId === highlightedRunId.value,
    )
    group?.scrollIntoView?.({ block: 'start' })
  }

  let landed = false
  function land() {
    landed = true
    side.value = sideCounts.value.staging > 0 ? 'staging' : 'implementation'
    revealHighlightedRun()
    consumeArrival()
  }

  const ONE_SHOT_FLAGS = ['detail', 'review', 'decide']
  watch(
    () => `${ONE_SHOT_FLAGS.map((flag) => route.query[flag] ?? '').join('|')}|${arrivalProjectId.value ?? ''}`,
    () => {
      if (!landed || !ONE_SHOT_FLAGS.some((flag) => route.query[flag] === '1')) return
      consumeArrival()
    },
  )

  return {
    side,
    selectSide,
    sideOf,
    sideOfRun,
    sideCounts,
    sideProjects,
    sideUnreviewed,
    sideChainRunIds,
    countLine,
    statusCounts,
    arrivalProjectId,
    highlightedRunId,
    land,
  }
}
