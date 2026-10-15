import { watch } from 'vue'
import { useProjectStore } from '@/stores/projects'
import { resolveTaxonomyColor } from '@/utils/taxonomyBadge'

export function useThreadProjectBadges(visibleThreads) {
  const projectStore = useProjectStore()
  const requested = new Set()

  watch(
    visibleThreads,
    (threads) => {
      for (const t of threads) {
        const id = t.project_id
        if (!id || requested.has(id)) continue
        if (projectStore.projectById(id)?.taxonomy_alias) continue
        requested.add(id)
        projectStore.fetchProject(id)
      }
    },
    { immediate: true },
  )

  function projectBadgeFor(thread) {
    if (!thread.project_id) return {}
    const project = projectStore.projectById(thread.project_id)
    if (!project?.taxonomy_alias) return {}
    return {
      _projectAlias: project.taxonomy_alias,
      _projectColor: resolveTaxonomyColor({
        abbreviation: project.project_type?.abbreviation,
        alias: project.taxonomy_alias,
        color: project.project_type?.color,
      }),
    }
  }

  return { projectBadgeFor }
}
