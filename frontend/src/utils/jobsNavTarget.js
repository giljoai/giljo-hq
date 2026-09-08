/**
 * jobsNavTarget.js — FE-6165f
 *
 * Pure (Vue-free) helpers for the NavigationDrawer Jobs nav item:
 *   - resolving the Jobs link destination (branch C > A > B precedence)
 *   - detecting whether the current route should highlight the Jobs item
 *   - building the Hub unread-count badge style object
 *
 * Extracted from NavigationDrawer.vue to keep that component under the 800-line
 * repository file-size guardrail without any behaviour change.
 *
 * Branch precedence (C > A > D > B):
 *   C: activeRun      → /projects/<headPid>?run=<runId>  (the /jobs multi variant)
 *   A: ONE active project → /projects/<id>?via=jobs      (solo project page, unchanged)
 *   D: SEVERAL active projects → /jobs                    (FE-9525d sectioned viewport)
 *   B: none            → /launch?via=jobs                 (launch page)
 *
 * FE-6173 removed the old "branch C" which pointed at the (now-deleted)
 * /mission-control route. FE-6174c REINSTATES a chain branch — but it now resolves
 * to the FE-6174b /jobs multi variant (the solo ProjectLaunch route carrying
 * ?run=<id>, which lights up useChainContext's conditional chain layer), NOT a
 * bespoke cockpit route. So an active chain takes the user to the live chain view
 * without a dead route.
 *
 * FE-9525d: BE-9525a/b retired the single-active-project-per-product invariant,
 * so branch A can no longer assume "the" active project. `activeProjects` (the
 * full list) is now the source of truth for the count; `activeProject` (its
 * first entry) is kept only for the chain-membership check below and the
 * count===1 case, so a single-project tenant's nav target is byte-identical to
 * before this project.
 *
 * Edition scope: CE.
 */
import { getAgentColor } from '@/config/agentColors'
import { hexToRgba } from '@/utils/colorUtils'

/**
 * Resolve the path the Jobs nav item should link to.
 *
 * @param {Object} ctx
 * @param {{ id: string } | null | undefined} ctx.activeProject  the FIRST active project (back-compat; used for the chain-membership check and the count===1 case)
 * @param {Array<{ id: string }>} [ctx.activeProjects]  the FULL list of active projects for the viewed product (FE-9525d). Omit for old single-project callers -- treated as [activeProject] when absent.
 * @param {{ id: string, resolved_order?: string[], project_ids?: string[] } | null | undefined} [ctx.activeRun]
 *        an in-flight chain run (sequenceRunStore); when present it wins.
 * @returns {string}
 */
export function resolveJobsNavPath({ activeProject, activeProjects, activeRun } = {}) {
  // Branch C (FE-6174c): an in-flight chain run routes to the ACTIVE member's
  // /jobs multi view. Active member = resolved_order[current_index] (FE-6221b
  // mid-flight-entry fix — landing on member 1 when the chain is already driving
  // member 3 was a UX dead-end). Falls back to resolved_order[0] for unstarted
  // runs, then to project_ids[0] when resolved_order is empty.
  //
  // BE-6200 (Unit E): a stale/wedged run must NOT hijack the nav when the user
  // has an active project elsewhere. Only honor branch C when the run CONTAINS
  // the active project (or when there is no active project to defer to). The BE
  // already filters all-terminal runs out of activeRuns; this is the FE guard
  // for the case where an active project and an unrelated run coexist.
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
    // NOT '/jobs' -- that bare path is a pre-existing legacy-redirect alias to
    // /launch?via=jobs (jobsRedirect.spec.js pins it).
    return '/jobs-overview'
  }
  if (activeProject) {
    return `/projects/${activeProject.id}?via=jobs`
  }
  return '/launch?via=jobs'
}

/**
 * Return true when the current route should highlight the Jobs nav item.
 *
 * Matches:
 *   - any path that includes /projects/  (solo project view)
 *   - any path with ?via=jobs            (deep-linked via the Jobs nav)
 *
 * @param {string} path   - current route.path
 * @param {Record<string, string>} query - current route.query
 * @returns {boolean}
 */
export function isJobsRouteActive(path, query) {
  if (query?.via === 'jobs') return true
  if (path.startsWith('/projects/')) return true
  return false
}

/**
 * Icon asset paths for the Jobs nav item. Active = the colourised Giljo face,
 * inactive = the dark/gray face. No hardcoded colours — the SVGs carry the brand
 * palette (design-system rule).
 */
export const JOBS_NAV_ICON_ACTIVE = '/icons/Giljo_YW_Face.svg'
export const JOBS_NAV_ICON_INACTIVE = '/icons/Giljo_Inactive_Dark.svg'

/**
 * Resolve the Jobs nav ICON off the SAME predicate that drives the nav-item
 * HIGHLIGHT (isJobsRouteActive), so the two can never drift.
 *
 * FE-9110: previously the icon keyed off a narrower `route.path.includes('/projects/')`
 * check while the highlight used isJobsRouteActive(path, query). On /launch?via=jobs
 * the item highlighted but the icon stayed gray. Keying both off isJobsRouteActive
 * fixes the divergence at the source.
 *
 * @param {string} path   - current route.path
 * @param {Record<string, string>} query - current route.query
 * @returns {string} the icon asset path (active when the Jobs route is active)
 */
export function resolveJobsNavIcon(path, query) {
  return isJobsRouteActive(path, query) ? JOBS_NAV_ICON_ACTIVE : JOBS_NAV_ICON_INACTIVE
}

/**
 * Style object for the Hub unread-count badge rendered in the nav list.
 * Uses the 'implementer' agent colour at 20 % opacity for the background.
 *
 * @returns {Record<string, string>}
 */
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
