/**
 * jobsNavTarget.spec.js — FE-6165f
 *
 * Unit tests for the pure Jobs-nav helpers extracted from NavigationDrawer.vue.
 * No Vue / store / router imports — pure function tests only.
 *
 * Edition scope: CE.
 */
import { describe, it, expect } from 'vitest'
import {
  resolveJobsNavPath,
  isJobsRouteActive,
  resolveJobsNavIcon,
  JOBS_NAV_ICON_ACTIVE,
  JOBS_NAV_ICON_INACTIVE,
} from '@/utils/jobsNavTarget'

// ── resolveJobsNavPath ───────────────────────────────────────────────────────

describe('resolveJobsNavPath', () => {
  // FE-6174c: branch C reinstated — an in-flight chain run now resolves to the
  // /jobs multi variant (/projects/<headPid>?run=<id>), NOT the retired
  // /mission-control route. Precedence C > A > B.
  // BE-6200 (Unit E): branch C only wins when the run CONTAINS the active
  // project — so a stale/wedged run can't hijack the nav away from the user's
  // real active project.
  it('branch C: returns /projects/<headPid>?run=<id> when the run contains the active project', () => {
    const result = resolveJobsNavPath({
      activeProject: { id: 'head' },
      activeRun: { id: 'run-7', resolved_order: ['head', 'tail'] },
    })
    expect(result).toBe('/projects/head?run=run-7')
  })

  it('branch C: returns the run path when there is no active project to defer to', () => {
    const result = resolveJobsNavPath({
      activeProject: null,
      activeRun: { id: 'run-7', resolved_order: ['head', 'tail'] },
    })
    expect(result).toBe('/projects/head?run=run-7')
  })

  it('branch C IGNORED: a run that does NOT contain the active project falls through to branch A (BE-6200)', () => {
    const result = resolveJobsNavPath({
      activeProject: { id: 'solo' },
      activeRun: { id: 'run-stale', resolved_order: ['wedged1', 'wedged2'] },
    })
    expect(result).toBe('/projects/solo?via=jobs')
  })

  it('branch C: falls back to project_ids[0] for the head when resolved_order is empty', () => {
    const result = resolveJobsNavPath({
      activeProject: null,
      activeRun: { id: 'run-8', resolved_order: [], project_ids: ['pA', 'pB'] },
    })
    expect(result).toBe('/projects/pA?run=run-8')
  })

  it('branch C: matches the active project via project_ids when resolved_order is empty', () => {
    const result = resolveJobsNavPath({
      activeProject: { id: 'pB' },
      activeRun: { id: 'run-8', resolved_order: [], project_ids: ['pA', 'pB'] },
    })
    expect(result).toBe('/projects/pA?run=run-8')
  })

  it('branch C ignored when the run has no resolvable head (falls through to A)', () => {
    const result = resolveJobsNavPath({
      activeProject: { id: 'p1' },
      activeRun: { id: 'run-9', resolved_order: [], project_ids: [] },
    })
    expect(result).toBe('/projects/p1?via=jobs')
  })

  // FE-6221b: mid-flight-entry fix. When a chain is already driving member N,
  // clicking JOBS must land on member N (not member 0 / the head). The run's
  // current_index drives the active member selection.
  it('branch C: mid-flight entry — lands on the active member (current_index), not the head', () => {
    const result = resolveJobsNavPath({
      activeProject: { id: 'p2' },
      activeRun: { id: 'run-mf', resolved_order: ['p1', 'p2', 'p3'], current_index: 1, project_ids: [] },
    })
    expect(result).toBe('/projects/p2?run=run-mf') // member at index 1, not the head (p1)
  })

  it('branch C: mid-flight entry falls back to head (index 0) when current_index is 0', () => {
    const result = resolveJobsNavPath({
      activeProject: null,
      activeRun: { id: 'run-mf2', resolved_order: ['p1', 'p2'], current_index: 0, project_ids: [] },
    })
    expect(result).toBe('/projects/p1?run=run-mf2')
  })

  it('branch C: mid-flight entry falls back to resolved_order[0] when current_index is absent', () => {
    // No current_index on the run object (e.g. older run records pre-FE-6221b)
    const result = resolveJobsNavPath({
      activeProject: null,
      activeRun: { id: 'run-mf3', resolved_order: ['p1', 'p2'], project_ids: [] },
    })
    expect(result).toBe('/projects/p1?run=run-mf3')
  })

  it('branch A: returns /projects/<id>?via=jobs when a project is active and no chain run', () => {
    const result = resolveJobsNavPath({
      activeProject: { id: 'p1' },
      activeRun: null,
    })
    expect(result).toBe('/projects/p1?via=jobs')
  })

  it('branch B: returns /launch?via=jobs when no active project', () => {
    const result = resolveJobsNavPath({
      activeProject: null,
    })
    expect(result).toBe('/launch?via=jobs')
  })

  it('branch B: returns /launch?via=jobs when activeProject is undefined', () => {
    const result = resolveJobsNavPath({
      activeProject: undefined,
    })
    expect(result).toBe('/launch?via=jobs')
  })

  // FE-9525d: branch D — several active projects at once (BE-9525a/b retired
  // the single-active-project-per-product invariant) route to the sectioned
  // Jobs viewport instead of an arbitrary single project.
  describe('branch D (FE-9525d: several active projects)', () => {
    it('returns /jobs-overview when activeProjects has more than one entry', () => {
      const result = resolveJobsNavPath({
        activeProject: { id: 'p1' },
        activeProjects: [{ id: 'p1' }, { id: 'p2' }],
      })
      expect(result).toBe('/jobs-overview')
    })

    it('still returns the single-project path when activeProjects has exactly one entry (byte-identical)', () => {
      const result = resolveJobsNavPath({
        activeProject: { id: 'solo' },
        activeProjects: [{ id: 'solo' }],
      })
      expect(result).toBe('/projects/solo?via=jobs')
    })

    it('omitting activeProjects falls back to the single-project behaviour (back-compat)', () => {
      const result = resolveJobsNavPath({
        activeProject: { id: 'solo' },
      })
      expect(result).toBe('/projects/solo?via=jobs')
    })

    it('branch C (an in-flight chain run) still wins over branch D', () => {
      const result = resolveJobsNavPath({
        activeProject: { id: 'p1' },
        activeProjects: [{ id: 'p1' }, { id: 'p2' }],
        activeRun: { id: 'run-1', resolved_order: ['p1', 'p2'] },
      })
      expect(result).toBe('/projects/p1?run=run-1')
    })
  })
})

// ── isJobsRouteActive ────────────────────────────────────────────────────────

describe('isJobsRouteActive', () => {
  // FE-6173: /mission-control no longer highlights the Jobs nav (branch C removed).
  it('returns false for /mission-control even with a run query param', () => {
    expect(isJobsRouteActive('/mission-control', { run: 'r1' })).toBe(false)
    expect(isJobsRouteActive('/mission-control', {})).toBe(false)
  })

  it('returns true for any path with ?via=jobs', () => {
    expect(isJobsRouteActive('/projects/p1', { via: 'jobs' })).toBe(true)
    expect(isJobsRouteActive('/launch', { via: 'jobs' })).toBe(true)
  })

  it('returns true for paths starting with /projects/', () => {
    expect(isJobsRouteActive('/projects/abc123', {})).toBe(true)
    expect(isJobsRouteActive('/projects/abc123/details', {})).toBe(true)
  })

  it('returns false for /projects (list page, no trailing slash + id)', () => {
    expect(isJobsRouteActive('/projects', {})).toBe(false)
  })

  it('returns false for unrelated paths', () => {
    expect(isJobsRouteActive('/home', {})).toBe(false)
    expect(isJobsRouteActive('/tasks', {})).toBe(false)
    expect(isJobsRouteActive('/roadmap', {})).toBe(false)
  })
})

// ── resolveJobsNavIcon ───────────────────────────────────────────────────────

describe('resolveJobsNavIcon', () => {
  // FE-9110: the icon MUST key off the same predicate as the highlight
  // (isJobsRouteActive), so the colourised icon shows exactly when the Jobs nav
  // item is highlighted — never gray-while-active. Truth table below.
  const ACTIVE = [
    ['/projects/<id> solo view', '/projects/abc123', {}],
    ['/projects/<id>?run= chain member', '/projects/abc123', { run: 'run-7' }],
    ['/projects/<id>/details nested', '/projects/abc123/details', {}],
    ['/launch?via=jobs (the FE-9110 bug)', '/launch', { via: 'jobs' }],
    ['/projects/<id>?via=jobs', '/projects/abc123', { via: 'jobs' }],
  ]
  const GRAY = [
    ['/launch (no via)', '/launch', {}],
    ['/hub', '/hub', {}],
    ['/tasks', '/tasks', {}],
    ['/projects list page', '/projects', {}],
    ['/home', '/home', {}],
  ]

  it.each(ACTIVE)('colourises the icon for %s', (_label, path, query) => {
    expect(resolveJobsNavIcon(path, query)).toBe(JOBS_NAV_ICON_ACTIVE)
  })

  it.each(GRAY)('grays the icon for %s', (_label, path, query) => {
    expect(resolveJobsNavIcon(path, query)).toBe(JOBS_NAV_ICON_INACTIVE)
  })

  // The load-bearing invariant: icon-active iff isJobsRouteActive. If these two
  // ever disagree the FE-9110 drift is back.
  it('is active iff isJobsRouteActive is true (no drift)', () => {
    const cases = [...ACTIVE, ...GRAY]
    for (const [, path, query] of cases) {
      const iconActive = resolveJobsNavIcon(path, query) === JOBS_NAV_ICON_ACTIVE
      expect(iconActive).toBe(isJobsRouteActive(path, query))
    }
  })
})
