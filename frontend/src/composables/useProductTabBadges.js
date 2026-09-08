/**
 * useProductTabBadges.js — FE-9502d
 *
 * Pure mapping: every open product tab gets a badgeCount, EXCEPT the
 * viewed tab (whatever activity happened while you were looking at it is
 * not "background" activity -- it already hydrated the stores you're
 * looking at). productActivityStore.clearActivity(viewedId) already runs on
 * switch, so this exclusion is defense-in-depth, not the primary mechanism.
 *
 * Kept as a standalone pure function (not inlined into DefaultLayout.vue's
 * computed) so it is unit-testable without mounting the whole layout.
 */
export function withProductActivityBadges(tabs, viewedId, getCount) {
  if (!Array.isArray(tabs)) return []
  return tabs.map((tab) => ({
    ...tab,
    badgeCount: tab.id === viewedId ? 0 : getCount(tab.id),
  }))
}
