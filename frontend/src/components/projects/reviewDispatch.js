
export function buildChainAwareShowCloseout(chainCtx, currentChainTab, showCloseoutButton) {
  if (chainCtx) {
    return Boolean(currentChainTab?.needsReview)
  }
  return showCloseoutButton
}

export function buildReviewDispatcher(chainCtx, currentChainTab, handleTabReview, openCloseoutModal) {
  if (chainCtx && currentChainTab) {
    return () => handleTabReview(currentChainTab)
  }
  return () => openCloseoutModal()
}

export function buildChainAwareProjectDoneStatus(chainCtx, currentChainTab, projectDoneStatus) {
  if (!chainCtx) return projectDoneStatus
  return (currentChainTab?.isCompleted && !currentChainTab.needsReview) ? 'completed' : null
}
