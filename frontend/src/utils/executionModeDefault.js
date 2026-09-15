
export const EXECUTION_MODE_DEFAULT_ASK = 'ask'

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

export const EXECUTION_MODE_DEFAULT_CHOICES = EXECUTION_MODE_DEFAULT_OPTIONS.map((o) => o.value)
