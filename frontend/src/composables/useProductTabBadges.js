export function withProductActivityBadges(tabs, viewedId, getCount) {
  if (!Array.isArray(tabs)) return []
  return tabs.map((tab) => ({
    ...tab,
    badgeCount: tab.id === viewedId ? 0 : getCount(tab.id),
  }))
}
