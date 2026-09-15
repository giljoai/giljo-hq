import { describe, it, expect } from 'vitest'
import {
  resolveJobsNavPath,
  isJobsRouteActive,
  resolveJobsNavIcon,
  JOBS_NAV_ICON_ACTIVE,
  JOBS_NAV_ICON_INACTIVE,
} from '@/utils/jobsNavTarget'


describe('resolveJobsNavPath', () => {
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

  it('branch C: mid-flight entry — lands on the active member (current_index), not the head', () => {
    const result = resolveJobsNavPath({
      activeProject: { id: 'p2' },
      activeRun: { id: 'run-mf', resolved_order: ['p1', 'p2', 'p3'], current_index: 1, project_ids: [] },
    })
    expect(result).toBe('/projects/p2?run=run-mf')
  })

  it('branch C: mid-flight entry falls back to head (index 0) when current_index is 0', () => {
    const result = resolveJobsNavPath({
      activeProject: null,
      activeRun: { id: 'run-mf2', resolved_order: ['p1', 'p2'], current_index: 0, project_ids: [] },
    })
    expect(result).toBe('/projects/p1?run=run-mf2')
  })

  it('branch C: mid-flight entry falls back to resolved_order[0] when current_index is absent', () => {
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


describe('isJobsRouteActive', () => {
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


describe('resolveJobsNavIcon', () => {
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

  it('is active iff isJobsRouteActive is true (no drift)', () => {
    const cases = [...ACTIVE, ...GRAY]
    for (const [, path, query] of cases) {
      const iconActive = resolveJobsNavIcon(path, query) === JOBS_NAV_ICON_ACTIVE
      expect(iconActive).toBe(isJobsRouteActive(path, query))
    }
  })
})
