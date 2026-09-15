
const RETIRED_HARNESS_NAMES = Object.freeze({
  gemini: 'Gemini',
  antigravity: 'Antigravity',
  gemini_cli: 'Gemini CLI',
  antigravity_cli: 'Antigravity CLI',
})

const GENERIC_CLI_TOOL = 'generic'

function isRetiredHarness(token) {
  return typeof token === 'string' && Object.hasOwn(RETIRED_HARNESS_NAMES, token)
}

export function retiredHarnessLabel(token) {
  return isRetiredHarness(token) ? `Generic (was ${RETIRED_HARNESS_NAMES[token]})` : null
}

export function foldRetiredHarness(token) {
  return isRetiredHarness(token) ? GENERIC_CLI_TOOL : token
}
