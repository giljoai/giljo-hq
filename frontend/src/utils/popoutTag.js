/**
 * popoutTag.js — FE-9553
 *
 * The one derivation of a browser popout's `tag`.
 *
 * Ruling 4(c) says popouts follow banner state including its death, which needs
 * two things of a tag: the OS must REPLACE a repeat of the same signal instead
 * of stacking a second notification, and whatever notices the banner clearing
 * must be able to name the popout it needs to close.
 *
 * Both require the tag to be a pure function of the signal. That is why this
 * lives in its own module rather than inline at the call site: the code that
 * OPENS a popout and the code that CLOSES it are in different places, and if
 * they each derived the tag their own way, a drift between them would show up
 * as a popout that can never be dismissed -- silently, and only on a real OS.
 *
 * Edition Scope: Both
 */

/** Namespace prefix, so a tag of ours is recognisable among any other origin's. */
const PREFIX = 'giljo-hub'

/**
 * The stable tag for one signal on one thread.
 *
 * @param {string} reason - BATON_FOCUS | MENTION_FOCUS | APPROVAL_FOCUS
 * @param {string} threadId - the thread the signal points at
 * @returns {string} a stable, addressable tag
 */
export function popoutTag(reason, threadId) {
  return `${PREFIX}:${reason || 'baton'}:${threadId || 'unknown'}`
}
