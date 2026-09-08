import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'

// ---------- Stub heavy dependencies ----------
// FE-9204: the connect step was rebuilt into a walk-one-tool-at-a-time controller
// (SetupStep2Connect) hosting the shared ConnectToolCard. These specs mount the step
// and exercise the CARD through it (the child is intentionally not stubbed). The
// pre-rebuild invariants are preserved under the new anatomy: no "OAuth" in copy
// (FE-6259b), CE never renders sign-in (FE-6242), server lock on SaaS/unknown
// (FE-6055), and stable data-testid hooks (FE-6247).

// Capture the WebSocket subscription so tests can fire setup:tool_connected.
let wsHandlers = {}
vi.mock('@/stores/websocket', () => ({
  useWebSocketStore: () => ({
    on: (event, handler) => {
      wsHandlers[event] = handler
      return () => {}
    },
  }),
}))

// FE-9569: credential-status seeding (detector 1). Defaults to "nothing
// connected yet" so the pre-existing suite (which never anticipated this
// call) keeps behaving exactly as before; individual tests below override
// per-call to exercise the already-connected seed path.
let mockConnectedHarnesses = {}

// BE-9591: the flow now requires a FRESH connection, so seeds must be expressed
// RELATIVE to now, never as fixed dates. A hardcoded "recent" literal silently
// becomes history as the calendar moves -- 2026-09-01 read as fresh when these
// tests were written and does not any more.
const justNow = () => new Date(Date.now() + 60_000).toISOString()
const longAgo = () => new Date(Date.now() - 86_400_000).toISOString()
vi.mock('@/services/api', () => ({
  default: {
    apiKeys: {
      getActive: vi.fn().mockResolvedValue({ data: [] }),
      create: vi.fn().mockResolvedValue({ data: { api_key: 'gk_test_key_123' } }),
    },
    connect: {
      credentialStatus: vi.fn(() =>
        Promise.resolve({
          data: {
            has_valid_api_key: false,
            has_valid_oauth: false,
            has_expired_oauth: false,
            connected_harnesses: mockConnectedHarnesses,
          },
        }),
      ),
    },
  },
}))

// configService.fetchConfig drives edition (CE editable / SaaS read-only).
let mockGiljoMode = 'saas'
let mockSslEnabled = false
vi.mock('@/services/configService', () => ({
  default: {
    fetchConfig: vi.fn().mockImplementation(() =>
      Promise.resolve({
        api: { host: 'localhost', port: '7272', protocol: mockSslEnabled ? 'https' : 'http', ssl_enabled: mockSslEnabled },
        giljo_mode: mockGiljoMode,
      }),
    ),
  },
}))

vi.mock('@/composables/useClipboard', () => ({
  useClipboard: () => ({ copy: vi.fn().mockResolvedValue(true) }),
}))

vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: vi.fn() }),
}))

// useMcpConfig is consumed REAL — the command generation is part of what we validate.

const globalStubs = {
  'v-text-field': {
    template: '<input class="v-text-field-stub" :value="modelValue" @click="$emit(\'click\', $event)" />',
    props: ['modelValue'],
    emits: ['click', 'update:modelValue'],
  },
  'v-icon': { template: '<i class="v-icon-stub"><slot /></i>' },
  'v-btn': {
    template: '<button class="v-btn-stub" @click="$emit(\'click\', $event)"><slot /></button>',
    emits: ['click'],
  },
  'v-progress-circular': { template: '<span class="v-progress-stub" />' },
  'v-alert': { template: '<div class="v-alert-stub"><slot /></div>' },
  'v-expand-transition': { template: '<div><slot /></div>' },
  'v-tooltip': { template: '<div><slot name="activator" :props="{}" /><slot /></div>' },
}

async function mountStep(selectedTools, giljoMode = 'saas') {
  mockGiljoMode = giljoMode
  const SetupStep2Connect = (await import('@/components/setup/SetupStep2Connect.vue')).default
  const wrapper = mount(SetupStep2Connect, {
    props: { selectedTools },
    global: { stubs: globalStubs },
  })
  await flushPromises() // onMounted: checkExistingKey + loadBackendConfig (parent + card)
  return wrapper
}

async function mountStepSsl(selectedTools, sslEnabled = false) {
  mockGiljoMode = 'saas'
  mockSslEnabled = sslEnabled
  const SetupStep2Connect = (await import('@/components/setup/SetupStep2Connect.vue')).default
  const wrapper = mount(SetupStep2Connect, {
    props: { selectedTools },
    global: { stubs: globalStubs },
  })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  wsHandlers = {}
  mockGiljoMode = 'saas'
  mockSslEnabled = false
  mockConnectedHarnesses = {}
})

// -----------------------------------------------------------------------

describe('SetupStep2Connect — SaaS: sign-in primary path (FE-6259b vocabulary lock)', () => {
  it('renders the sign-in command with NO bearer token and never the word "OAuth"', async () => {
    const wrapper = await mountStep(['claude_code'], 'saas')
    const pre = wrapper.find('pre.config-code')
    expect(pre.exists()).toBe(true)
    expect(pre.text()).toContain('claude mcp add')
    expect(pre.text()).toContain('/mcp')
    expect(pre.text()).not.toContain('Bearer')
    expect(pre.text()).not.toContain('Authorization')
    // Connect-vocabulary parity: never the word "OAuth", never an em dash in step-2 copy.
    expect(wrapper.text()).not.toContain('OAuth')
    expect(wrapper.text()).not.toContain('—')
  })

  it('keeps the API key flow behind a quiet fallback toggle (hidden by default)', async () => {
    const wrapper = await mountStep(['claude_code'], 'saas')
    expect(wrapper.text()).toContain('Use an API key instead')
    expect(wrapper.text()).not.toContain('Generate API Key')

    await wrapper.find('[data-testid="fallback-toggle"]').trigger('click')
    await nextTick()
    expect(wrapper.text()).toContain('Generate API Key')
    // Toggling back returns to sign-in.
    await wrapper.find('[data-testid="fallback-toggle"]').trigger('click')
    await nextTick()
    expect(wrapper.text()).toContain('Use an API key instead')
  })

  it('never surfaces the oauth_quirk_note (would leak "OAuth" into user copy)', async () => {
    const wrapper = await mountStep(['codex_cli'], 'saas')
    expect(wrapper.text()).not.toContain('auto-detected')
    expect(wrapper.text()).not.toContain('OAuth')
  })

  it('treats Antigravity as key-only — no sign-in command, shows the not-supported note + immediate key flow', async () => {
    const wrapper = await mountStep(['antigravity_cli'], 'saas')
    const text = wrapper.text()
    expect(wrapper.find('[data-testid="oauth-section"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="fallback-toggle"]').exists()).toBe(false)
    expect(text).toContain('Browser sign-in is not supported')
    expect(text).not.toContain('OAuth')
    expect(text).toContain('Generate API Key')
  })

  it('OpenCode (added FE-9204) is sign-in-capable — emits the opencode add+auth command, no bearer', async () => {
    const wrapper = await mountStep(['opencode'], 'saas')
    const pre = wrapper.find('pre.config-code')
    expect(pre.text()).toContain('opencode mcp add giljo_hq')
    expect(pre.text()).toContain('opencode mcp auth giljo_hq')
    expect(pre.text()).not.toContain('Bearer')
    expect(wrapper.find('[data-testid="fallback-toggle"]').exists()).toBe(true)
  })

  it('Generic MCP client (FE-9204) is manual-config — shows the JSON server config, no sign-in command', async () => {
    const wrapper = await mountStep(['generic'], 'saas')
    expect(wrapper.find('[data-testid="oauth-section"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="fallback-toggle"]').exists()).toBe(false)
    // Manual config shows the generate card immediately; the JSON appears once a key exists.
    expect(wrapper.text()).toContain('Generate API Key')
  })

  // FE-9225: the retired configurator's "Web & app" route is ported (reduced) onto the
  // generic card — apps that take an MCP connector URL need the bare endpoint, not the
  // key-bearing JSON, because they run their own browser sign-in.
  it('Generic MCP client exposes the connector URL + web-app hint, with no key required', async () => {
    const wrapper = await mountStep(['generic'], 'saas')
    const block = wrapper.find('[data-testid="web-endpoint-block"]')
    expect(block.exists()).toBe(true)
    // buildServerUrl path 1: browser is already on the backend host, so the endpoint
    // is origin-derived (this is what proxied deployments depend on).
    expect(block.find('pre').text()).toBe(`${window.location.origin}/mcp`)
    expect(block.find('[data-testid="web-endpoint-copy-btn"]').exists()).toBe(true)
    expect(block.text()).toContain('claude.ai')
    // Present before any key is generated — the web connector never needs one.
    expect(wrapper.text()).toContain('Generate API Key')
  })

  it('does NOT show the connector URL block for a CLI tool', async () => {
    const wrapper = await mountStep(['claude_code'], 'saas')
    expect(wrapper.find('[data-testid="web-endpoint-block"]').exists()).toBe(false)
  })
})

// -----------------------------------------------------------------------

/**
 * FE-9569 detector 1: the connect dot used to depend ENTIRELY on a live
 * setup:tool_connected WS event arriving while this card is open. An
 * already-authenticated tenant (connected in another TUI, or reconnecting
 * after a reload) sends no `initialize` while the wizard is mounted, so the
 * dot stayed stuck on "Waiting..." forever even though a real connection
 * already exists. Fix: seed connectionStatus from the durable
 * GET /api/connect/credential-status truth on mount (same idiom already
 * shipped in ToolsConnectDirectory.vue), with the WS event staying as the
 * live-delta path on top of that seed. By design: no recency cutoff on
 * connected_harnesses — any timestamp counts, matching the shipped sibling.
 */
describe('SetupStep2Connect — credential-status seeding, already-connected case (FE-9569 detector 1)', () => {
  it('fresh case: no connected_harnesses leaves the dot waiting (unchanged behavior)', async () => {
    mockConnectedHarnesses = {}
    const wrapper = await mountStep(['claude_code'], 'saas')
    expect(wrapper.find('[data-testid="hero-check"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('Waiting for')
  })

  it('a FRESH connection on record flips the dot green WITHOUT any WS event', async () => {
    // MEANING NARROWED BY BE-9591. This used to assert that ANY connection on record
    // flips the dot, however old. The operator hit the other side of that: he connected
    // on one machine, opened the wizard on a second, and the tool was already green
    // before that machine had ever connected. The guarantee it actually protects --
    // don't depend on catching a live WS event -- is unchanged and still asserted here;
    // what changed is that the record must be FRESH. See the historical-record test below.
    // 'claude-code' is the backend harness_resolver token for claude_code (setupTools.js HARNESS_TO_TOOL_ID).
    mockConnectedHarnesses = { 'claude-code': justNow() }
    const wrapper = await mountStep(['claude_code'], 'saas')
    expect(wrapper.find('[data-testid="hero-check"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('connected.')
    // No setup:tool_connected fired -- this must NOT depend on the event.
    expect(wsHandlers['setup:tool_connected']).toBeTruthy()
  })

  it('a fresh connection unblocks can-proceed on mount, no click needed', async () => {
    mockConnectedHarnesses = { 'claude-code': justNow() }
    const wrapper = await mountStep(['claude_code'], 'saas')
    const canProceed = wrapper.emitted('can-proceed')
    expect(canProceed[canProceed.length - 1]).toEqual([true])
  })

  it('multi-tool walk: resumes at the first NOT-yet-connected tool, not always index 0', async () => {
    mockConnectedHarnesses = { 'claude-code': justNow() }
    const wrapper = await mountStep(['claude_code', 'codex_cli'], 'saas')
    // claude_code (tool 1) is already connected via credential-status, so the
    // walk should resume on codex_cli (tool 2), not restart at tool 1.
    expect(wrapper.find('.connect-eyebrow').text()).toContain('TOOL 2 OF 2')
  })

  it('an unrecognized/generic harness does not crash and does not falsely flip a named tool', async () => {
    mockConnectedHarnesses = { generic: justNow() }
    const wrapper = await mountStep(['claude_code'], 'saas')
    expect(wrapper.find('[data-testid="hero-check"]').exists()).toBe(false)
  })

  it('BE-9591: a HISTORICAL connection does NOT satisfy this flow', async () => {
    // The operator's report: connected on PC1, opened the wizard on a laptop, and
    // Claude Code was already green there before the laptop had ever connected.
    // Once-connected read as forever-connected. The active flow now requires a
    // connection newer than the moment the step was entered.
    mockConnectedHarnesses = { 'claude-code': longAgo() }
    const wrapper = await mountStep(['claude_code'], 'saas')
    expect(wrapper.find('[data-testid="hero-check"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('Waiting for')
  })

  it('BE-9591: a live WS announce still flips it, history or not', async () => {
    // The freshness cutoff must never swallow the live path -- an announce arriving
    // WHILE the step is open is fresh by definition, and it is the signal a user
    // connecting right now actually produces.
    mockConnectedHarnesses = { 'claude-code': longAgo() }
    const wrapper = await mountStep(['claude_code'], 'saas')
    expect(wrapper.find('[data-testid="hero-check"]').exists()).toBe(false)

    wsHandlers['setup:tool_connected']({ tool_name: 'claude-code' })
    await nextTick()

    expect(wrapper.find('[data-testid="hero-check"]').exists()).toBe(true)
  })

  it('a credential-status fetch failure degrades gracefully to the pre-fix waiting state', async () => {
    const apiModule = (await import('@/services/api')).default
    apiModule.connect.credentialStatus.mockRejectedValueOnce(new Error('network down'))
    const wrapper = await mountStep(['claude_code'], 'saas')
    expect(wrapper.text()).toContain('Waiting for')
  })
})

// -----------------------------------------------------------------------

describe('SetupStep2Connect — CE: API-key-only gating (FE-6242)', () => {
  it('CE: hides the sign-in command + fallback toggle for a sign-in-capable tool', async () => {
    const wrapper = await mountStep(['claude_code'], 'ce')
    expect(wrapper.find('[data-testid="oauth-section"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="fallback-toggle"]').exists()).toBe(false)
  })

  it('CE: shows the API-key flow immediately without toggling', async () => {
    const wrapper = await mountStep(['claude_code'], 'ce')
    expect(wrapper.text()).toContain('Generate API Key')
  })

  it('CE: Antigravity (key-only) still works — key-only note + immediate key flow', async () => {
    const wrapper = await mountStep(['antigravity_cli'], 'ce')
    expect(wrapper.text()).toContain('Browser sign-in is not supported')
    expect(wrapper.text()).toContain('Generate API Key')
  })

  it('CE: WS connect event flips the active tool and clears the can-proceed gate', async () => {
    const wrapper = await mountStep(['claude_code'], 'ce')
    expect(typeof wsHandlers['setup:tool_connected']).toBe('function')
    wsHandlers['setup:tool_connected']({ tool_name: 'mcp_connected' })
    await nextTick()
    const canProceed = wrapper.emitted('can-proceed')
    expect(canProceed[canProceed.length - 1]).toEqual([true])
  })
})

// -----------------------------------------------------------------------

describe('SetupStep2Connect — status hero + generic-event active-only flip (proposal §6)', () => {
  it('starts waiting and blocks proceeding', async () => {
    const wrapper = await mountStep(['claude_code'], 'saas')
    expect(wrapper.text()).toContain('Waiting for')
    const canProceed = wrapper.emitted('can-proceed')
    expect(canProceed[canProceed.length - 1]).toEqual([false])
  })

  it('flips to connected + can-proceed=true when the generic event fires', async () => {
    const wrapper = await mountStep(['claude_code'], 'saas')
    wsHandlers['setup:tool_connected']({ tool_name: 'mcp_connected' })
    await nextTick()
    expect(wrapper.find('[data-testid="hero-check"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('connected.')
    const stepData = wrapper.emitted('step-data')
    expect(stepData[stepData.length - 1][0].connectedTools).toContain('claude_code')
  })

  it('generic event flips ONLY the active tool, not every selected tool', async () => {
    const wrapper = await mountStep(['claude_code', 'codex_cli'], 'saas')
    // Active tool is the first one (claude_code); the event flips it only.
    wsHandlers['setup:tool_connected']({ tool_name: 'mcp_connected' })
    await nextTick()
    const stepData = wrapper.emitted('step-data')
    const latest = stepData[stepData.length - 1][0].connectedTools
    expect(latest).toContain('claude_code')
    expect(latest).not.toContain('codex_cli')
  })

  it('advance label is "Next tool" mid-walk and "Install agents & skills" on the last tool', async () => {
    const wrapper = await mountStep(['claude_code', 'codex_cli'], 'saas')
    // Connect the active (first) tool → hero advance appears with the mid-walk label.
    wsHandlers['setup:tool_connected']({ tool_name: 'mcp_connected' })
    await nextTick()
    expect(wrapper.find('[data-testid="hero-advance"]').text()).toContain('Next tool')
    // Walk to the last tool, connect it → label becomes the install advance.
    await wrapper.find('[data-testid="hero-advance"]').trigger('click')
    await nextTick()
    expect(wrapper.find('.connect-eyebrow').text()).toContain('TOOL 2 OF 2')
    wsHandlers['setup:tool_connected']({ tool_name: 'mcp_connected' })
    await nextTick()
    expect(wrapper.find('[data-testid="hero-advance"]').text()).toContain('Install agents & skills')
  })

  it('"I already configured this" marks the ACTIVE tool only (ratified change from marks-all)', async () => {
    const wrapper = await mountStep(['claude_code', 'codex_cli'], 'saas')
    await wrapper.find('[data-testid="already-configured"]').trigger('click')
    await nextTick()
    const stepData = wrapper.emitted('step-data')
    const latest = stepData[stepData.length - 1][0].connectedTools
    expect(latest).toEqual(['claude_code'])
  })

  it('advancing to the last tool then advancing again emits advance-step (wizard forward)', async () => {
    const wrapper = await mountStep(['claude_code'], 'saas')
    wsHandlers['setup:tool_connected']({ tool_name: 'mcp_connected' })
    await nextTick()
    await wrapper.find('[data-testid="hero-advance"]').trigger('click')
    await nextTick()
    expect(wrapper.emitted('advance-step')).toBeTruthy()
  })
})

// -----------------------------------------------------------------------

describe('SetupStep2Connect — per-tool fallback isolation (walk)', () => {
  it('toggling the fallback on one tool does not carry to the next tool', async () => {
    const wrapper = await mountStep(['claude_code', 'codex_cli'], 'saas')
    // Reveal the key flow on tool 1.
    await wrapper.find('[data-testid="fallback-toggle"]').trigger('click')
    await nextTick()
    expect(wrapper.text()).toContain('Generate API Key')
    // Connect + walk to tool 2 — it must start on the sign-in path, not the key flow.
    wsHandlers['setup:tool_connected']({ tool_name: 'mcp_connected' })
    await nextTick()
    await wrapper.find('[data-testid="hero-advance"]').trigger('click')
    await nextTick()
    expect(wrapper.find('.connect-eyebrow').text()).toContain('TOOL 2 OF 2')
    expect(wrapper.text()).toContain('Use an API key instead')
    expect(wrapper.text()).not.toContain('Generate API Key')
  })
})

// -----------------------------------------------------------------------

describe('SetupStep2Connect — server URL edition gating (FE-6055)', () => {
  it('is editable (click reveals host/port fields, pencil icon) on CE', async () => {
    const wrapper = await mountStep(['claude_code'], 'ce')
    expect(wrapper.find('[data-testid="server-url-pencil"]').exists()).toBe(true)
    expect(wrapper.find('.server-edit-fields').exists()).toBe(false)
    await wrapper.find('[data-testid="server-url-pencil"]').trigger('click')
    await nextTick()
    expect(wrapper.find('.server-edit-fields').exists()).toBe(true)
  })

  it('is read-only (lock icon, no edit reveal) on SaaS', async () => {
    const wrapper = await mountStep(['claude_code'], 'saas')
    expect(wrapper.find('[data-testid="server-url-lock"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="server-url-pencil"]').exists()).toBe(false)
  })
})

// -----------------------------------------------------------------------

describe('SetupStep2Connect — HTTPS cert-trust guidance (INF-6241)', () => {
  it('shows no cert-trust note when ssl_enabled is false', async () => {
    const wrapper = await mountStepSsl(['claude_code'], false)
    expect(wrapper.find('[data-testid="oauth-cert-note"]').exists()).toBe(false)
  })

  it('shows a cert-trust note when ssl_enabled is true', async () => {
    const wrapper = await mountStepSsl(['claude_code'], true)
    expect(wrapper.find('[data-testid="oauth-cert-note"]').exists()).toBe(true)
    const text = wrapper.find('[data-testid="oauth-cert-note"]').text()
    expect(text).toContain('HTTPS certificate trust')
    // Never imply GiljoAI issued the cert.
    expect(text).not.toContain('root CA')
    expect(text).not.toContain('mkcert')
  })
})

// -----------------------------------------------------------------------

describe('SetupStep2Connect — data-testid hooks preserved under new anatomy (FE-6247)', () => {
  it('root, server field, and status hero hooks are present', async () => {
    const wrapper = await mountStep(['claude_code'], 'saas')
    expect(wrapper.find('[data-testid="step2-connect"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="server-url-field"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="status-hero"]').exists()).toBe(true)
  })

  it('SaaS + sign-in tool: oauth-section + fallback-toggle hooks present', async () => {
    const wrapper = await mountStep(['claude_code'], 'saas')
    expect(wrapper.find('[data-testid="oauth-section"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="fallback-toggle"]').exists()).toBe(true)
  })

  it('CE: oauth-section + fallback-toggle hooks absent', async () => {
    const wrapper = await mountStep(['claude_code'], 'ce')
    expect(wrapper.find('[data-testid="oauth-section"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="fallback-toggle"]').exists()).toBe(false)
  })

  it('key-only tool: apikey-only-note present, oauth-section absent', async () => {
    const wrapper = await mountStep(['antigravity_cli'], 'saas')
    expect(wrapper.find('[data-testid="apikey-only-note"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="oauth-section"]').exists()).toBe(false)
  })

  it('SaaS + HTTPS: oauth-cert-note renders when ssl_enabled', async () => {
    const wrapper = await mountStepSsl(['claude_code'], true)
    expect(wrapper.find('[data-testid="oauth-cert-note"]').exists()).toBe(true)
  })
})

// -----------------------------------------------------------------------

/**
 * FE-9383 — OpenCode's `mcp add` does not share Claude Code's syntax: the server URL
 * rides on `--url` (a bare URL is an unexpected positional and OpenCode answers with
 * its help text), and headers are KEY=VALUE (`Authorization=Bearer <key>`, not the
 * colon form). Both generators emitted the Claude Code shape, so an OpenCode user's
 * first copy-paste failed twice over. These assertions sit at the rendered-snippet
 * layer — the exact text the user copies — and pin the Claude Code commands as
 * unchanged so the fix cannot drift into the tool it was already correct for.
 */
describe('SetupStep2Connect — OpenCode snippet syntax + client labels (FE-9383)', () => {
  /** Run the key flow so the bearer command block renders (it is gated on hasKey). */
  async function withGeneratedKey(wrapper) {
    await wrapper.find('[data-testid="generate-key-btn"]').trigger('click')
    await flushPromises()
    await nextTick()
    return wrapper
  }

  it('sign-in snippet passes the URL with --url, never as a bare positional', async () => {
    const wrapper = await mountStep(['opencode'], 'saas')
    const snippet = wrapper.find('[data-testid="oauth-section"] pre').text()
    expect(snippet).toMatch(/opencode mcp add giljo_hq --url https?:\/\/\S+\/mcp/)
    expect(snippet).not.toMatch(/mcp add giljo_hq https?:/)
    expect(snippet).toContain('opencode mcp auth giljo_hq')
  })

  it('bearer snippet uses --url and the KEY=VALUE header, never the colon form', async () => {
    const wrapper = await withGeneratedKey(await mountStep(['opencode'], 'ce'))
    const snippet = wrapper.find('[data-testid="config-command-block"] pre').text()
    expect(snippet).toMatch(/opencode mcp add giljo_hq --url https?:\/\/\S+\/mcp/)
    expect(snippet).toContain('Authorization=Bearer gk_test_key_123')
    expect(snippet).not.toContain('Authorization: Bearer')
    expect(snippet).not.toMatch(/mcp add giljo_hq https?:/)
  })

  it('leaves the Claude Code snippets alone — positional URL and colon header stay', async () => {
    const saas = await mountStep(['claude_code'], 'saas')
    expect(saas.find('[data-testid="oauth-section"] pre').text()).toMatch(
      /^claude mcp add --transport http giljo_hq https?:\/\/\S+\/mcp --scope user$/,
    )

    const ce = await withGeneratedKey(await mountStep(['claude_code'], 'ce'))
    const snippet = ce.find('[data-testid="config-command-block"] pre').text()
    expect(snippet).toMatch(
      /^claude mcp add --scope user --transport http giljo_hq https?:\/\/\S+\/mcp --header "Authorization: Bearer gk_test_key_123"$/,
    )
    expect(snippet).not.toContain('--url')
  })

  it('names the client on every snippet it hands out', async () => {
    const saas = await mountStep(['opencode'], 'saas')
    expect(saas.find('[data-testid="oauth-command-label"]').text()).toContain('OpenCode')

    const ceOpencode = await withGeneratedKey(await mountStep(['opencode'], 'ce'))
    expect(ceOpencode.find('[data-testid="config-block-label"]').text()).toContain('OpenCode')

    const ceClaude = await withGeneratedKey(await mountStep(['claude_code'], 'ce'))
    expect(ceClaude.find('[data-testid="config-block-label"]').text()).toContain('Claude Code')
  })
})
