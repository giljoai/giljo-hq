/**
 * giljo-internal/no-toast-for-agent-events
 *
 * A toast is feedback for the USER's own action: past tense, seconds long,
 * "your click worked". FE-9553's binding rule is that every event lives on
 * exactly one live surface, and an agent-initiated event's surface is the
 * banner (with the bell as its durable record) — never the toast.
 *
 * WHY A LINT RULE AND NOT A CONVENTION. All 219 toast call sites funnel through
 * one choke point, `useToast().showToast`, so the invariant is cheap to state
 * and impossible to hold by discipline alone: nothing about calling showToast
 * from a WebSocket handler looks wrong at the call site, and the four-surface
 * sprawl FE-9553 exists to undo was built exactly that way, one reasonable
 * addition at a time. Per the repo's mechanism-vs-prose rule, if a careful
 * author could do everything right and still produce the defect, it is a
 * mechanism gap. This is the mechanism.
 *
 * WHAT IT FLAGS: a toast raised from a file whose whole job is reacting to
 * something the server said UNBIDDEN — the WebSocket event routes, the router
 * passes, and the socket store itself. A frame arrives there whether or not the
 * operator is doing anything, so a toast is announcing the agents' action as
 * though it were the user's.
 *
 * WHAT IT DELIBERATELY DOES NOT DO: try to decide, at an arbitrary call site,
 * whether the surrounding function was reached from a click. That is not
 * decidable from the AST — `refreshJobs()` is called from a button AND from a
 * watcher — and a rule that guessed would either miss the real cases or cry
 * wolf on the 203 legitimate ones. The undecidable cases were migrated by hand
 * with a human reading each one; this rule's job is narrower and exact: keep the
 * paths that can ONLY be server-driven toast-free, so the seventeenth violation
 * cannot be added silently.
 *
 * Scope note: the flagged directories are the ones where a toast is *always*
 * wrong. A view or component may legitimately toast, so they are not covered
 * here — for those, the review question is "is this reachable from a click",
 * which a human answers.
 */
'use strict'

/**
 * Path fragments whose contents are, by construction, reacting to something the
 * server said UNBIDDEN. Matched against the normalized filename.
 *
 * The test each entry must pass: could this code run when nobody clicked
 * anything? A WebSocket frame arrives whether or not the operator is doing
 * something, so a toast there is announcing the agents' action as if it were
 * the user's.
 *
 * AXIOS RESPONSE INTERCEPTORS ARE DELIBERATELY *NOT* HERE, and I had them in
 * this list on the first draft. They failed the test above the moment the rule
 * ran: an HTTP response arrives BECAUSE someone made a request, so the
 * interceptor is usually the tail end of a user's own click. The rule flagged
 * `installLicenseStateInterceptor`'s lapsed-subscription toast, which fires
 * when the operator attempts a write and the server refuses it — that is
 * textbook feedback for the user's own action and the toast is exactly right.
 * Including interceptors would have enshrined a wrong invariant in a lint rule,
 * which is worse than a wrong test: it makes every future author work around
 * it, and the natural workaround is a disable comment that erodes the rule's
 * meaning.
 */
const SERVER_DRIVEN_PATHS = [
  '/stores/eventroutes/', // the WebSocket event route table
  '/stores/websocket.js', // the socket itself: connect/disconnect/reconnect
  '/stores/websocketeventrouter.js', // the router passes
]

function isServerDrivenFile(filename) {
  if (!filename) return false
  const lower = filename.replace(/\\/g, '/').toLowerCase()
  if (lower.includes('.spec.')) return false
  return SERVER_DRIVEN_PATHS.some((fragment) => lower.includes(fragment))
}

/** `showToast(...)`, `toast.showToast(...)`, `window.$toast.warning(...)`. */
function toastCalleeName(node) {
  const callee = node.callee
  if (!callee) return null
  if (callee.type === 'Identifier') {
    return callee.name === 'showToast' ? 'showToast' : null
  }
  if (callee.type === 'MemberExpression' && callee.property?.type === 'Identifier') {
    const prop = callee.property.name
    if (prop === 'showToast') return 'showToast'
    // The imperative global, used by non-Vue module code.
    const objectText = callee.object?.property?.name || callee.object?.name
    if (objectText === '$toast') return `$toast.${prop}`
  }
  return null
}

module.exports = {
  meta: {
    type: 'problem',
    docs: {
      description:
        'Server-driven code must not raise a toast: an agent-initiated event belongs to the banner and the bell (FE-9553).',
    },
    schema: [],
    messages: {
      agentToast:
        'A toast is feedback for the user\'s OWN action, and this file only ever reacts to the server ({{ what }}). An agent-initiated event belongs on the banner, with the bell as its durable record — see FE-9553 and stores/notificationSignalRouter.js. If the operator genuinely needs to know, announce it on the surface that survives being missed.',
    },
  },

  create(context) {
    const filename = context.filename || context.getFilename?.() || ''
    if (!isServerDrivenFile(filename)) return {}

    return {
      CallExpression(node) {
        const what = toastCalleeName(node)
        if (!what) return
        context.report({ node, messageId: 'agentToast', data: { what } })
      },
    }
  },
}
