import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { immutableMapSet, immutableObjectPatch } from './immutableHelpers'
import api from '@/services/api'

function resolveProjectId(value) {
  if (!value) return null
  if (typeof value === 'string') return value
  return value.id || value.project_id || null
}

function normalizeProjectState(project) {
  const projectId = resolveProjectId(project)
  if (!projectId) return null

  const ss = project?.staging_status
  const implLaunchedAt = project?.implementationLaunchedAt || project?.implementation_launched_at || null
  return {
    project_id: projectId,
    mission: project?.mission || '',
    status: project?.status || null,
    execution_mode: project?.execution_mode || null,
    stagingComplete: Boolean(project?.stagingComplete) || ss === 'staging_complete' || false,
    isStaged: Boolean(project?.isStaged) || ss === 'staged' || false,
    isStaging: Boolean(project?.isStaging) || ss === 'staging' || false,
    isLaunched: Boolean(project?.isLaunched) || false,
    implementationLaunched: Boolean(project?.implementationLaunched) || Boolean(implLaunchedAt) || false,
    implementationLaunchedAt: implLaunchedAt,
  }
}

export const useProjectStateStore = defineStore('projectStateDomain', () => {
  const stateByProjectId = ref(new Map())

  const allProjects = computed(() => Array.from(stateByProjectId.value.values()))

  function getProjectState(projectId) {
    const resolved = resolveProjectId(projectId)
    if (!resolved) return null
    return allProjects.value.find((p) => p.project_id === resolved) || null
  }

  function upsertProjectState(projectId, patch) {
    const resolved = resolveProjectId(projectId)
    if (!resolved) return

    const previous = stateByProjectId.value.get(resolved)
    const base =
      previous ||
      normalizeProjectState({ id: resolved }) || {
        project_id: resolved,
        mission: '',
        status: null,
        execution_mode: null,
        stagingComplete: false,
        isStaged: false,
        isStaging: false,
        isLaunched: false,
        implementationLaunched: false,
        implementationLaunchedAt: null,
      }

    const next = immutableObjectPatch(base, patch)

    if (previous && JSON.stringify(previous) === JSON.stringify(next)) {
      return
    }

    stateByProjectId.value = immutableMapSet(stateByProjectId.value, resolved, next)
  }

  function setProject(project) {
    const normalized = normalizeProjectState(project)
    if (!normalized) return

    const previous = stateByProjectId.value.get(normalized.project_id)

    let next
    if (previous) {
      const patched = immutableObjectPatch(previous, normalized)

      next = {
        ...patched,
        stagingComplete: previous.stagingComplete || normalized.stagingComplete,
        implementationLaunched: previous.implementationLaunched || normalized.implementationLaunched,
        implementationLaunchedAt: previous.implementationLaunchedAt || normalized.implementationLaunchedAt,
        isLaunched: previous.isLaunched || normalized.isLaunched,
      }
    } else {
      next = normalized
    }

    stateByProjectId.value = immutableMapSet(stateByProjectId.value, normalized.project_id, next)
  }

  function setStagingComplete(projectId, complete = true) {
    const patch = { stagingComplete: Boolean(complete) }
    if (complete) patch.isStaging = false
    upsertProjectState(projectId, patch)
  }

  function setMission(projectId, mission) {
    upsertProjectState(projectId, { mission: mission || '' })
  }

  function setIsStaged(projectId, isStaged) {
    upsertProjectState(projectId, { isStaged: Boolean(isStaged) })
  }

  function setIsStaging(projectId, isStaging) {
    upsertProjectState(projectId, { isStaging: Boolean(isStaging) })
  }

  function setLaunched(projectId, isLaunched) {
    upsertProjectState(projectId, { isLaunched: Boolean(isLaunched) })
  }

  function setImplementationLaunched(projectId, timestamp, source = null) {
    upsertProjectState(projectId, {
      implementationLaunched: Boolean(timestamp),
      implementationLaunchedAt: timestamp || null,
      lastLaunchSource: source || null,
    })
  }

  async function restageProject(projectId) {
    const resolved = resolveProjectId(projectId)
    if (!resolved) return

    await api.projects.restage(resolved)
    upsertProjectState(resolved, {
      isStaged: false,
      isStaging: false,
      stagingComplete: false,
      mission: '',
      implementationLaunched: false,
      implementationLaunchedAt: null,
    })
  }

  async function unstageProject(projectId) {
    const resolved = resolveProjectId(projectId)
    if (!resolved) return

    await api.projects.unstage(resolved)
    upsertProjectState(resolved, {
      isStaged: false,
      isStaging: false,
      mission: '',
    })
  }


  function handleMissionUpdated(payload) {
    const projectId = payload?.project_id || payload?.id
    if (!projectId) return
    setMission(projectId, payload?.mission || '')
    if (payload?.mission) {
      upsertProjectState(projectId, { isStaged: false, isStaging: true })
    }
  }

  function handleStagingComplete(payload) {
    const projectId = payload?.project_id
    if (!projectId) return
    setStagingComplete(projectId, true)
  }

  function handleImplementationLaunched(payload) {
    const projectId = payload?.project_id
    if (!projectId) return
    setImplementationLaunched(projectId, payload?.implementation_launched_at || null, payload?.source || null)
  }

  function $reset() {
    stateByProjectId.value = new Map()
  }

  return {
    stateByProjectId,

    getProjectState,

    setProject,
    setStagingComplete,
    setMission,
    setIsStaged,
    setIsStaging,
    setLaunched,
    setImplementationLaunched,
    restageProject,
    unstageProject,

    handleMissionUpdated,
    handleStagingComplete,
    handleImplementationLaunched,

    $reset,
  }
})
