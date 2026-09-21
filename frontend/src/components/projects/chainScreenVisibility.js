
const UNSTARTED_MEMBER_STATUSES = new Set(['', 'pending', 'staged'])
const FINISHED_MEMBER_STATUSES = new Set(['completed', 'failed', 'terminated', 'cancelled'])

export function buildChainScreenControls(chainCtx, isRunning) {
  if (!chainCtx) {
    return {
      showModeSelector: false,
      showStageButton: false,
      showImplementButton: false,
      showStopChain: false,
      showModeLabel: false,
      modeLabel: '',
    }
  }

  const mode = chainCtx.run?.execution_mode || ''
  return {
    showModeSelector: !isRunning,
    showStageButton: !isRunning,
    showImplementButton: !isRunning,
    showStopChain: isRunning,
    showModeLabel: isRunning && Boolean(mode),
    modeLabel: mode,
  }
}

export function buildStopChainEffects(run) {
  const effects = { completed: [], underway: [], unstarted: [] }
  if (!run) return effects

  const order = run.resolved_order?.length ? run.resolved_order : run.project_ids || []
  const statuses = run.project_statuses || {}

  order.forEach((pid, index) => {
    const position = index + 1
    const status = statuses[pid] ?? ''
    if (FINISHED_MEMBER_STATUSES.has(status)) {
      effects.completed.push(position)
    } else if (UNSTARTED_MEMBER_STATUSES.has(status)) {
      effects.unstarted.push(position)
    } else {
      effects.underway.push(position)
    }
  })

  return effects
}
