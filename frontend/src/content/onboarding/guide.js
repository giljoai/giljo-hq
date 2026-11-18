import {
  ONBOARDING_INTRO_VIDEO,
  ONBOARDING_LESSONS,
  ONBOARDING_SETUP_HELPER,
} from '@/content/onboarding/videos'

export const SETUP_REQUEST =
  'Please run giljo_setup from the Giljo HQ MCP server and follow its setup instructions.'

export const GUIDE_VIDEOS = Object.freeze([
  ONBOARDING_INTRO_VIDEO,
  ONBOARDING_SETUP_HELPER,
  ...ONBOARDING_LESSONS,
])

export const NUDGE_AFTER_MS = 5 * 60 * 1000

export const GUIDE_TEXT = Object.freeze({
  title: 'Getting started',
  finished: 'Congratulations. You are set up and ran your first project.',
  finishedAgain: 'You can open this guide again in Tools > Learning.',
  finishedClose: 'Close guide',
  copied: 'Copied',
  fold: 'Fold the guide',
  unfold: 'Open the guide',
  close: 'Close the guide',
  openMobile: 'Getting started',
  needsProduct: 'These need a product first. Add one in step 3.',
  needsProject: 'Create a project in step 4 first.',
  askYourTool: 'Or ask your AI tool to make a project.',
  connectedBefore: 'Connected before. Connect again when you are ready.',
  count: (done, total) => `${done} of ${total}`,
  goToProjects: 'Go to Projects',
  watch: (title, length) => `Watch how: ${title} (${length})`,
  watchLink: (length) => `Watch how (${length})`,
  nudge: 'Stuck? The video shows each press.',
  showCard: 'Show me the card',
  stageTodo: 'In Projects, press the play button on your project. Pick a mode, then press Stage.',
  stageRequested: 'Prompt copied. Paste it in your AI tool. Your tool writes the plan.',
  builtTodo: 'Press the Implement button on your project card.',
  builtInProgress: 'In progress.',
  builtAwaitingReview: 'Your agents are done. Press Review project on the card to see their work.',
  builtDone: 'First project finished and reviewed.',
  dot: (n, title, state, current) => {
    const words = {
      done: 'done',
      requested: 'prompt copied',
      in_progress: 'in progress',
      awaiting_review: 'waiting for your review',
      todo: current ? 'current step' : 'not done',
      current: 'current step',
    }
    return `Step ${n}: ${title}, ${words[state]}`
  },
})

const MODE_WORDS = Object.freeze({
  subagent: 'sub-agent mode',
  multi_terminal: 'multi-terminal mode',
})

const CONNECT = Object.freeze({ id: 'connect', label: 'Connect' })

function toolDone(r) {
  if (!r.live) return GUIDE_TEXT.connectedBefore
  return r.tool_name ? `${r.tool_name} is connected.` : 'An AI tool is connected.'
}

function stagedDone(r) {
  const mode = MODE_WORDS[r.mode]
  return mode ? `Staged (${mode}). The plan waits for your go.` : 'Staged. The plan waits for your go.'
}

function videoLength(video) {
  const total = Math.round(video.seconds)
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}

function stagePhase(r) {
  if (r.done) return 'done'
  return r.requested === true ? 'requested' : 'todo'
}

function builtPhase(r) {
  if (r.done) return 'done'
  if (r.awaiting_review === true) return 'awaiting_review'
  return r.in_progress ? 'in_progress' : 'todo'
}

export function buildGuideRows(rows) {
  const projectId = rows.project_created?.project_id ?? null
  const stage = stagePhase(rows.project_staged)
  const built = builtPhase(rows.project_built)
  const defs = [
    {
      key: 'tool_connected',
      title: 'Connect your AI tool',
      done: rows.tool_connected.done,
      doneLine: toolDone(rows.tool_connected),
      help: 'Giljo HQ works through the AI tool you already use.',
      actions: !rows.tool_connected.done || !rows.tool_connected.live ? [CONNECT] : [],
    },
    {
      key: 'skills_installed',
      title: 'Set up Giljo HQ in your tool',
      done: rows.skills_installed.done,
      doneLine: 'Setup done.',
      help: 'Ask your tool to run giljo_setup.',
      actions: rows.skills_installed.done ? [] : [{ id: 'copy', label: 'Copy the request' }],
    },
    {
      key: 'product_exists',
      title: 'Add your product',
      done: rows.product_exists.done,
      doneLine: rows.product_exists.product_name
        ? `Product added: ${rows.product_exists.product_name}.`
        : 'Product added.',
      help: 'Your AI tool can fill it in from your code.',
      actions: rows.product_exists.done ? [] : [{ id: 'product', label: 'Choose how to start' }],
    },
    {
      key: 'project_created',
      title: 'Create your first project',
      done: !!rows.project_created?.done,
      doneLine: rows.project_created?.project_name
        ? `Project created: ${rows.project_created.project_name}.`
        : 'Project created.',
      help: '',
      actions: rows.project_created?.done
        ? []
        : [
            { id: 'import', label: 'Import an existing product' },
            { id: 'bootstrap', label: 'Bootstrap a new product' },
          ],
      extraLine: GUIDE_TEXT.askYourTool,
      needsProduct: !rows.product_exists.done,
      needsProductLine: GUIDE_TEXT.needsProduct,
    },
    {
      key: 'project_staged',
      title: 'Stage your project',
      phase: stage,
      done: rows.project_staged.done,
      doneLine: stagedDone(rows.project_staged),
      help: projectId ? GUIDE_TEXT.stageTodo : GUIDE_TEXT.needsProject,
      phaseLine: { requested: GUIDE_TEXT.stageRequested },
      picture: projectId ? 'play' : null,
      actions: [],
      goToProjects: !!projectId,
    },
    {
      key: 'project_built',
      title: 'Finish your first project',
      phase: built,
      done: rows.project_built.done,
      doneLine: GUIDE_TEXT.builtDone,
      help: projectId ? GUIDE_TEXT.builtTodo : GUIDE_TEXT.needsProject,
      phaseLine: {
        in_progress: GUIDE_TEXT.builtInProgress,
        awaiting_review: GUIDE_TEXT.builtAwaitingReview,
      },
      picture: projectId ? 'implement' : null,
      phasePicture: { awaiting_review: 'review' },
      actions: [],
      goToProjects: !!projectId,
    },
  ]
  const currentIndex = defs.findIndex((d) => !d.done)
  return defs.map((d, i) => {
    const current = i === currentIndex
    const phase = d.phase ?? null
    const state = phase ?? (d.done ? 'done' : current ? 'current' : 'todo')
    const quiet = phase === null || phase === 'todo'
    const showHelp = current && quiet
    const phaseLine = phase && d.phaseLine ? d.phaseLine[phase] : ''
    let line = ''
    if (d.done) line = d.doneLine
    else if (phaseLine) line = phaseLine
    else if (showHelp) line = d.help
    const picture = d.done ? null : (phase && d.phasePicture?.[phase]) || (showHelp ? d.picture ?? null : null)
    return {
      n: i + 1,
      key: d.key,
      title: d.title,
      state,
      current,
      line,
      picture: line ? picture : null,
      actions: d.actions,
      goToProjects: !!d.goToProjects && !d.done && !!line && phase !== 'awaiting_review',
      showCard: d.key === 'project_built' && phase === 'awaiting_review',
      extraLine: d.extraLine ?? '',
      needsProduct: d.needsProduct ?? false,
      needsProductLine: d.needsProductLine ?? '',
      projectId,
      video: GUIDE_VIDEOS[i],
      videoLength: videoLength(GUIDE_VIDEOS[i]),
    }
  })
}
