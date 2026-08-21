/**
 * threadDisplayName.js — FE-9436
 *
 * What to CALL a thread in anything a human reads.
 *
 * Three surfaces were carrying this rule with three different answers, and the operator's
 * names-never-UUIDs ruling is precisely that they must not:
 *
 *   - the announcer (toast + browser notification + bell row) ended at `thread <uuid>`;
 *   - the app-wide banner ended at 'a thread';
 *   - the Hub's restore toast ended at the raw `thread_id`.
 *
 * Two of those put a UUID in front of the operator, and the third only avoided it by
 * accident of having been written later. A comment in SystemStatusBanner promises its
 * wording is "the Hub's, kept word for word so the two surfaces do not describe the same
 * event two different ways" — a promise no mechanism was keeping. This is the mechanism.
 *
 * The order is what a person would say: the thread's NAME first, then the serial they
 * would actually quote to an agent (CHT-0493), then plain words. The id never appears,
 * at any position — a UUID is not a worse name for a thread, it is not a name at all.
 *
 * Edition scope: Both
 */

/**
 * @param thread   the store's thread object, when the caller has one
 * @param payload  the live WS event, when the caller has one. It carries `subject` on a
 *                 rename and `chat_id` on every `thread_update`, so a hand-off can be
 *                 named even before the store has hydrated that thread — which is the
 *                 cold-page case the browser notification exists for, and exactly when
 *                 the old fallbacks reached for the id.
 */
export function threadDisplayName(thread, payload) {
  return (
    thread?.subject ||
    thread?.title ||
    payload?.subject ||
    payload?.chat_id ||
    thread?.chat_id ||
    'a thread'
  )
}
