import { getAgentColor } from '@/config/agentColors'
import { hexToRgba } from '@/utils/colorUtils'

export function resolveJobsNavPath({ activeProject, activeProjects, activeRun } = {}) {
  const activeMemberPid =
    (typeof activeRun?.current_index === 'number' && activeRun?.resolved_order?.[activeRun.current_index]) ||
    activeRun?.resolved_order?.[0] ||
    activeRun?.project_ids?.[0]
  const runMemberIds = [...(activeRun?.resolved_order || []), ...(activeRun?.project_ids || [])]
  const runContainsActiveProject = !!activeProject && runMemberIds.includes(activeProject.id)
  if (activeRun?.id && activeMemberPid && (!activeProject || runContainsActiveProject)) {
    return `/projects/${activeMemberPid}?run=${activeRun.id}`
  }
  const resolvedActiveProjects = activeProjects ?? (activeProject ? [activeProject] : [])
  if (resolvedActiveProjects.length > 1) {
    return '/jobs-overview'
  }
  if (activeProject) {
    return `/projects/${activeProject.id}?via=jobs`
  }
  return '/launch?via=jobs'
}

export function jobsNavPathToLocation(path) {
  const [pathname, search] = String(path || '').split('?')
  const query = Object.fromEntries(new URLSearchParams(search || ''))
  if (pathname.startsWith('/projects/')) {
    return {
      name: 'ProjectLaunch',
      params: { projectId: pathname.slice('/projects/'.length) },
      query,
    }
  }
  if (pathname === '/jobs-overview') {
    return { name: 'JobsViewport' }
  }
  return null
}

export function isJobsRouteActive(path, query) {
  if (query?.via === 'jobs') return true
  if (path.startsWith('/projects/')) return true
  return false
}

export const JOBS_NAV_ICON_ACTIVE = '/icons/Giljo_YW_Face.svg'
export const JOBS_NAV_ICON_INACTIVE = '/icons/Giljo_Inactive_Dark.svg'

export function resolveJobsNavIcon(path, query) {
  return isJobsRouteActive(path, query) ? JOBS_NAV_ICON_ACTIVE : JOBS_NAV_ICON_INACTIVE
}

export function hubUnreadBadgeStyle() {
  const hex = getAgentColor('implementer')?.hex
  return {
    backgroundColor: hexToRgba(hex, 0.2),
    color: hex,
    borderRadius: '8px',
    fontSize: '0.6rem',
    fontWeight: '700',
    padding: '1px 5px',
    minWidth: '16px',
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    lineHeight: '1',
  }
}
