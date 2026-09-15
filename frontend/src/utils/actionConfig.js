
export function shouldShowLaunchAction(job, claudeCodeCliMode) {
  if (claudeCodeCliMode && job.agent_display_name !== 'orchestrator') {
    return false
  }

  return true
}
