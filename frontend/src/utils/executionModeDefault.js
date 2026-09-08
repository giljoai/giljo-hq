/**
 * executionModeDefault.js — FE-9555
 *
 * The account's standing answer to the one question staging asks: should it ask
 * how the work runs every time, or always use the same mode?
 *
 * Ruling 6 of the FE-9555 design session: "Execution mode must be ASKED, both
 * doors." `stage_project` refuses an omitted mode rather than picking one, and the
 * dashboard's ExecutionModeSelector already stays null until the user chooses. A
 * refusal with no off switch is a nag, so the ruling pairs both with exactly ONE
 * account default, set under Tools -> Agents.
 *
 * Mirrors `src/giljo_mcp/execution_mode_default.py`. The two mode VALUES must stay
 * identical to the backend's VALID_EXECUTION_MODES — the labels are ours to word,
 * the tokens are not.
 *
 * Edition scope: Both.
 */

/** The stored value meaning "put the question to the user every time". */
export const EXECUTION_MODE_DEFAULT_ASK = 'ask'

/**
 * The three choices, in display order, with the wording the control shows.
 *
 * The descriptions are the same two sentences the headless refusal carries, on
 * purpose: a user who has been asked by their coding agent and then comes here to
 * stop being asked should recognise the options, not have to re-learn them.
 */
export const EXECUTION_MODE_DEFAULT_OPTIONS = [
  {
    value: EXECUTION_MODE_DEFAULT_ASK,
    title: 'Ask every time',
    subtitle: 'Staging asks how you want each run to work.',
  },
  {
    value: 'multi_terminal',
    title: 'Terminals',
    subtitle: 'A separate terminal per agent, and you watch the fleet.',
  },
  {
    value: 'subagent',
    title: 'Subagents',
    subtitle: 'One session drives the worker agents itself.',
  },
]

/** Just the stored tokens, for validating what the server hands back. */
export const EXECUTION_MODE_DEFAULT_CHOICES = EXECUTION_MODE_DEFAULT_OPTIONS.map((o) => o.value)
