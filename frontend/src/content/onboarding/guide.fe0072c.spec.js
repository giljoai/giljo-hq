import { describe, expect, it } from 'vitest'

import { buildGuideRows, GUIDE_VIDEOS, SETUP_REQUEST } from '@/content/onboarding/guide'
import { ONBOARDING_INTRO_VIDEO, ONBOARDING_SETUP_HELPER, ONBOARDING_LESSONS } from '@/content/onboarding/videos'
import { startListPayload, ALL_DONE } from '../../../tests/helpers/startListRows'

const rowsOf = (over) => buildGuideRows(startListPayload(over).rows)

describe('guide rows: shape', () => {
  it('has six rows with the agreed titles', () => {
    expect(rowsOf().map((r) => r.title)).toEqual([
      'Connect your AI tool',
      'Set up Giljo HQ in your tool',
      'Add your product',
      'Create your first project',
      'Stage your project',
      'Finish your first project',
    ])
  })

  it('maps each row to its video: intro, setup, lessons 1 to 4', () => {
    expect(GUIDE_VIDEOS).toEqual([
      ONBOARDING_INTRO_VIDEO,
      ONBOARDING_SETUP_HELPER,
      ...ONBOARDING_LESSONS,
    ])
    expect(rowsOf().map((r) => r.video.id)).toEqual([
      'how-to-get-going', 'setup', 'lesson01', 'lesson02', 'lesson03', 'lesson04',
    ])
  })

  it('the current row is the first one not done; only it has help', () => {
    const rows = rowsOf({ tool_connected: { done: true, live: true, tool_name: 'Codex' } })
    expect(rows.map((r) => r.state)).toEqual(['done', 'current', 'todo', 'todo', 'todo', 'todo'])
    expect(rows.map((r) => r.current)).toEqual([false, true, false, false, false, false])
    expect(rows[1].line).toBe('Ask your tool to run giljo_setup.')
    expect(rows[2].line).toBe('')
    expect(rows[3].line).toBe('')
  })

  it('the request text to copy is the existing giljo_setup request', () => {
    expect(SETUP_REQUEST).toBe(
      'Please run giljo_setup from the Giljo HQ MCP server and follow its setup instructions.',
    )
  })
})

describe('guide rows: row 1', () => {
  it('not done: Connect', () => {
    const r = rowsOf()[0]
    expect(r.state).toBe('current')
    expect(r.actions).toEqual([{ id: 'connect', label: 'Connect' }])
  })
  it('done and live: names the tool, no action', () => {
    const r = rowsOf({ tool_connected: { done: true, live: true, tool_name: 'Claude Code' } })[0]
    expect(r.state).toBe('done')
    expect(r.line).toBe('Claude Code is connected.')
    expect(r.actions).toEqual([])
  })
  it('done but not live: says it was connected before and offers Connect again', () => {
    const r = rowsOf({ tool_connected: { done: true, live: false, tool_name: 'Claude Code' } })[0]
    expect(r.state).toBe('done')
    expect(r.line).toBe('Connected before. Connect again when you are ready.')
    expect(r.actions).toEqual([{ id: 'connect', label: 'Connect' }])
  })
  it('live with no tool name still says something true', () => {
    const r = rowsOf({ tool_connected: { done: true, live: true, tool_name: null } })[0]
    expect(r.line).toBe('An AI tool is connected.')
  })
})

describe('guide rows: rows 2 and 3', () => {
  it('row 2: copy the request; done says Setup done.', () => {
    expect(rowsOf()[1].actions).toEqual([{ id: 'copy', label: 'Copy the request' }])
    const done = rowsOf({ skills_installed: { done: true } })[1]
    expect(done.line).toBe('Setup done.')
    expect(done.actions).toEqual([])
  })
  it('row 3: choose how to start; done names the product', () => {
    expect(rowsOf()[2].actions).toEqual([{ id: 'product', label: 'Choose how to start' }])
    const done = rowsOf({ product_exists: { done: true, product_name: 'Recipe Box' } })[2]
    expect(done.line).toBe('Product added: Recipe Box.')
  })
  it('a row after the current one still has its action (not locked)', () => {
    const rows = rowsOf()
    expect(rows[2].state).toBe('todo')
    expect(rows[2].actions).toHaveLength(1)
  })
  it('row 3 help text', () => {
    const rows = rowsOf({
      tool_connected: { done: true, live: true },
      skills_installed: { done: true },
    })
    expect(rows[2].line).toBe('Your AI tool can fill it in from your code.')
  })
})

describe('guide rows: row 4', () => {
  it('two starter buttons and the ask-your-tool line', () => {
    const r = rowsOf({ product_exists: { done: true, product_name: 'P' } })[3]
    expect(r.actions).toEqual([
      { id: 'import', label: 'Import an existing product' },
      { id: 'bootstrap', label: 'Bootstrap a new product' },
    ])
    expect(r.extraLine).toBe('Or ask your AI tool to make a project.')
    expect(r.needsProduct).toBe(false)
  })
  it('without a product it says what the buttons need', () => {
    const r = rowsOf()[3]
    expect(r.needsProduct).toBe(true)
    expect(r.needsProductLine).toBe('These need a product first. Add one in step 3.')
  })
  it('done names the project', () => {
    const r = rowsOf({ project_created: { done: true, project_id: 'p', project_name: 'Add a search box' } })[3]
    expect(r.line).toBe('Project created: Add a search box.')
    expect(r.actions).toEqual([])
  })
})

describe('guide rows: rows 5 and 6', () => {
  const upTo4 = {
    tool_connected: { done: true, live: true },
    skills_installed: { done: true },
    product_exists: { done: true, product_name: 'P' },
    project_created: { done: true, project_id: 'p-9', project_name: 'N' },
  }
  const staged = { ...upTo4, project_staged: { done: true, mode: 'subagent' } }

  it('row 5 todo: the play button instruction with a picture of it, no buttons', () => {
    const r = rowsOf(upTo4)[4]
    expect(r.state).toBe('todo')
    expect(r.current).toBe(true)
    expect(r.line).toBe('In Projects, press the play button on your project. Pick a mode, then press Stage.')
    expect(r.picture).toBe('play')
    expect(r.actions).toEqual([])
    expect(r.goToProjects).toBe(true)
    expect(r.projectId).toBe('p-9')
  })
  it('row 5 requested: the prompt was handed out, no plan yet', () => {
    const r = rowsOf({ ...upTo4, project_staged: { requested: true } })[4]
    expect(r.state).toBe('requested')
    expect(r.line).toBe('Prompt copied. Paste it in your AI tool. Your tool writes the plan.')
    expect(r.picture).toBe(null)
    expect(r.goToProjects).toBe(true)
  })
  it('row 5 requested is ignored once staged: done wins', () => {
    const r = rowsOf({ ...upTo4, project_staged: { done: true, requested: true, mode: 'subagent' } })[4]
    expect(r.state).toBe('done')
    expect(r.goToProjects).toBe(false)
  })
  it('row 5 done: the mode in plain words', () => {
    const sub = rowsOf({ ...upTo4, project_staged: { done: true, mode: 'subagent' } })[4]
    expect(sub.line).toBe('Staged (sub-agent mode). The plan waits for your go.')
    const multi = rowsOf({ ...upTo4, project_staged: { done: true, mode: 'multi_terminal' } })[4]
    expect(multi.line).toBe('Staged (multi-terminal mode). The plan waits for your go.')
    const unknown = rowsOf({ ...upTo4, project_staged: { done: true, mode: null } })[4]
    expect(unknown.line).toBe('Staged. The plan waits for your go.')
  })
  it('row 6 has the four states: todo, in_progress, awaiting_review, done', () => {
    const idle = rowsOf(staged)[5]
    expect(idle.state).toBe('todo')
    expect(idle.current).toBe(true)
    expect(idle.line).toBe('Press the Implement button on your project card.')
    expect(idle.picture).toBe('implement')
    const running = rowsOf({ ...staged, project_built: { done: false, in_progress: true } })[5]
    expect(running.state).toBe('in_progress')
    expect(running.line).toBe('In progress.')
    expect(running.picture).toBe(null)
    const review = rowsOf({ ...staged, project_built: { done: false, in_progress: false, awaiting_review: true } })[5]
    expect(review.state).toBe('awaiting_review')
    expect(review.line).toBe('Your agents are done. Press Review project on the card to see their work.')
    expect(review.picture).toBe('review')
    expect(review.goToProjects).toBe(false)
    expect(review.showCard).toBe(true)
    const done = rowsOf({ ...staged, project_built: { done: true, in_progress: false } })[5]
    expect(done.state).toBe('done')
    expect(done.line).toBe('First project finished and reviewed.')
    expect(done.picture).toBe(null)
    expect(done.goToProjects).toBe(false)
    expect(done.showCard).toBe(false)
  })
  it('built but not reviewed is NOT done: the count and the tick wait for the review', () => {
    const r = rowsOf({ ...staged, project_built: { done: false, awaiting_review: true } })[5]
    expect(r.state).not.toBe('done')
  })
  it('an old server (no requested, no awaiting_review): today\'s behaviour, no crash', () => {
    const rows = buildGuideRows({
      tool_connected: { done: true, live: true },
      skills_installed: { done: true },
      product_exists: { done: true },
      project_staged: { done: false },
      project_built: { done: false, in_progress: false },
    })
    expect(rows[4].state).toBe('todo')
    expect(rows[5].state).toBe('todo')
    expect(rows[3].current).toBe(true)
  })
  it('a cancelled run (in_progress false again) goes back to the Implement instruction', () => {
    const r = rowsOf({ ...staged, project_built: { done: false, in_progress: false } })[5]
    expect(r.line).toBe('Press the Implement button on your project card.')
  })
  it('with no project rows 5 and 6 have no link or picture, and the current one says what to do first', () => {
    const noProject = {
      ...upTo4,
      project_created: { done: true, project_id: null, project_name: null },
    }
    const five = rowsOf(noProject)[4]
    expect(five.current).toBe(true)
    expect(five.goToProjects).toBe(false)
    expect(five.picture).toBe(null)
    expect(five.line).toBe('Create a project in step 4 first.')
    const six = rowsOf({ ...noProject, project_staged: { done: true, mode: 'subagent' } })[5]
    expect(six.line).toBe('Create a project in step 4 first.')
    expect(six.goToProjects).toBe(false)
  })
  it('a row that is not current and untouched shows no line and no link', () => {
    const six = rowsOf(upTo4)[5]
    expect(six.line).toBe('')
    expect(six.goToProjects).toBe(false)
  })
  it('every row knows its video length as m:ss', () => {
    const rows = rowsOf()
    expect(rows[0].videoLength).toBe('1:48')
    expect(rows[1].videoLength).toBe('0:42')
  })
})

describe('guide rows: all done', () => {
  it('every row is done', () => {
    expect(buildGuideRows(ALL_DONE.rows).every((r) => r.state === 'done')).toBe(true)
  })
})
