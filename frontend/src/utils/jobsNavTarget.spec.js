import { describe, it, expect } from 'vitest'
import {
  resolveJobsNavPath,
  JOBS_BOARD_PATH,
  isJobsRouteActive,
  resolveJobsNavIcon,
  JOBS_NAV_ICON_ACTIVE,
  JOBS_NAV_ICON_INACTIVE,
} from '@/utils/jobsNavTarget'


describe('resolveJobsNavPath', () => {
  it('exports the board path as the single Jobs landing', () => {
    expect(JOBS_BOARD_PATH).toBe('/jobs-overview')
  })

  it('returns the board with no arguments at all', () => {
    expect(resolveJobsNavPath()).toBe('/jobs-overview')
  })

  const INPUTS = [
    ['no context at all (old branch B)', {}],
    ['activeProject null', { activeProject: null }],
    ['activeProject undefined', { activeProject: undefined }],
    ['exactly one active project (old branch A)', { activeProject: { id: 'solo' }, activeProjects: [{ id: 'solo' }] }],
    ['one active project, activeProjects omitted', { activeProject: { id: 'solo' } }],
    [
      'several active projects (old branch D)',
      { activeProject: { id: 'p1' }, activeProjects: [{ id: 'p1' }, { id: 'p2' }] },
    ],
    [
      'an in-flight chain containing the active project (old branch C)',
      { activeProject: { id: 'head' }, activeRun: { id: 'run-7', resolved_order: ['head', 'tail'] } },
    ],
    [
      'an in-flight chain with no active project to defer to',
      { activeProject: null, activeRun: { id: 'run-7', resolved_order: ['head', 'tail'] } },
    ],
    [
      'a stale chain that does NOT contain the active project (old BE-6200 carve-out)',
      { activeProject: { id: 'solo' }, activeRun: { id: 'run-stale', resolved_order: ['wedged1'] } },
    ],
    [
      'a chain known only by project_ids',
      { activeProject: null, activeRun: { id: 'run-8', resolved_order: [], project_ids: ['pA', 'pB'] } },
    ],
    [
      'a chain with no members',
      { activeProject: { id: 'p1' }, activeRun: { id: 'run-9', resolved_order: [], project_ids: [] } },
    ],
    [
      'mid-flight chain entry, whichever member runs',
      {
        activeProject: { id: 'p2' },
        activeProjects: [{ id: 'p2' }],
        activeRun: { id: 'run-mf', resolved_order: ['p1', 'p2', 'p3'], current_index: 1 },
      },
    ],
    [
      'several active projects AND an in-flight chain at once',
      {
        activeProject: { id: 'p1' },
        activeProjects: [{ id: 'p1' }, { id: 'p2' }],
        activeRun: { id: 'run-1', resolved_order: ['p1', 'p2'] },
      },
    ],
  ]

  it.each(INPUTS)('returns the board for %s', (_label, ctx) => {
    expect(resolveJobsNavPath(ctx)).toBe('/jobs-overview')
  })

  it('never resolves to a project page or the retired launch page', () => {
    for (const [, ctx] of INPUTS) {
      const path = resolveJobsNavPath(ctx)
      expect(path).not.toContain('/projects/')
      expect(path).not.toContain('/launch')
      expect(path).not.toContain('?run=')
    }
  })
})


describe('isJobsRouteActive', () => {
  it('returns false for /mission-control even with a run query param', () => {
    expect(isJobsRouteActive('/mission-control', { run: 'r1' })).toBe(false)
    expect(isJobsRouteActive('/mission-control', {})).toBe(false)
  })

  it('returns true for any path with ?via=jobs', () => {
    expect(isJobsRouteActive('/projects/p1', { via: 'jobs' })).toBe(true)
    expect(isJobsRouteActive('/hub', { via: 'jobs' })).toBe(true)
  })

  it('returns true on the Jobs board itself', () => {
    expect(isJobsRouteActive('/jobs-overview', {})).toBe(true)
    expect(isJobsRouteActive('/jobs-overview', { run: 'run-7' })).toBe(true)
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
    ['/hub?via=jobs (the FE-9110 bug shape)', '/hub', { via: 'jobs' }],
    ['/projects/<id>?via=jobs', '/projects/abc123', { via: 'jobs' }],
    ['/jobs-overview the board (FE-9655e)', '/jobs-overview', {}],
    ['/jobs-overview?run= a highlighted chain group', '/jobs-overview', { run: 'run-7' }],
  ]
  const GRAY = [
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
