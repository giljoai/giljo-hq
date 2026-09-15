import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'


let wsHandlers = {}
vi.mock('@/stores/websocket', () => ({
  useWebSocketStore: () => ({
    on: (event, handler) => {
      wsHandlers[event] = handler
      return () => {}
    },
  }),
}))

let mockConnectedHarnesses = {}

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
  await flushPromises()
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


describe('SetupStep2Connect — SaaS: sign-in primary path (FE-6259b vocabulary lock)', () => {
  it('renders the sign-in command with NO bearer token and never the word "OAuth"', async () => {
    const wrapper = await mountStep(['claude_code'], 'saas')
    const pre = wrapper.find('pre.config-code')
    expect(pre.exists()).toBe(true)
    expect(pre.text()).toContain('claude mcp add')
    expect(pre.text()).toContain('/mcp')
    expect(pre.text()).not.toContain('Bearer')
    expect(pre.text()).not.toContain('Authorization')
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
    await wrapper.find('[data-testid="fallback-toggle"]').trigger('click')
    await nextTick()
    expect(wrapper.text()).toContain('Use an API key instead')
  })

  it('never surfaces the oauth_quirk_note (would leak "OAuth" into user copy)', async () => {
    const wrapper = await mountStep(['codex_cli'], 'saas')
    expect(wrapper.text()).not.toContain('auto-detected')
    expect(wrapper.text()).not.toContain('OAuth')
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
    expect(wrapper.text()).toContain('Generate API Key')
  })

  it('Generic MCP client exposes the connector URL + web-app hint, with no key required', async () => {
    const wrapper = await mountStep(['generic'], 'saas')
    const block = wrapper.find('[data-testid="web-endpoint-block"]')
    expect(block.exists()).toBe(true)
    expect(block.find('pre').text()).toBe(`${window.location.origin}/mcp`)
    expect(block.find('[data-testid="web-endpoint-copy-btn"]').exists()).toBe(true)
    expect(block.text()).toContain('claude.ai')
    expect(wrapper.text()).toContain('Generate API Key')
  })

  it('does NOT show the connector URL block for a CLI tool', async () => {
    const wrapper = await mountStep(['claude_code'], 'saas')
    expect(wrapper.find('[data-testid="web-endpoint-block"]').exists()).toBe(false)
  })
})


describe('SetupStep2Connect — credential-status seeding, already-connected case (FE-9569 detector 1)', () => {
  it('fresh case: no connected_harnesses leaves the dot waiting (unchanged behavior)', async () => {
    mockConnectedHarnesses = {}
    const wrapper = await mountStep(['claude_code'], 'saas')
    expect(wrapper.find('[data-testid="hero-check"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('Waiting for')
  })

  it('a FRESH connection on record flips the dot green WITHOUT any WS event', async () => {
    mockConnectedHarnesses = { 'claude-code': justNow() }
    const wrapper = await mountStep(['claude_code'], 'saas')
    expect(wrapper.find('[data-testid="hero-check"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('connected.')
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
    expect(wrapper.find('.connect-eyebrow').text()).toContain('TOOL 2 OF 2')
  })

  it('an unrecognized/generic harness does not crash and does not falsely flip a named tool', async () => {
    mockConnectedHarnesses = { generic: justNow() }
    const wrapper = await mountStep(['claude_code'], 'saas')
    expect(wrapper.find('[data-testid="hero-check"]').exists()).toBe(false)
  })

  it('BE-9591: a HISTORICAL connection does NOT satisfy this flow', async () => {
    mockConnectedHarnesses = { 'claude-code': longAgo() }
    const wrapper = await mountStep(['claude_code'], 'saas')
    expect(wrapper.find('[data-testid="hero-check"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('Waiting for')
  })

  it('BE-9591: a live WS announce still flips it, history or not', async () => {
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

  it('CE: WS connect event flips the active tool and clears the can-proceed gate', async () => {
    const wrapper = await mountStep(['claude_code'], 'ce')
    expect(typeof wsHandlers['setup:tool_connected']).toBe('function')
    wsHandlers['setup:tool_connected']({ tool_name: 'mcp_connected' })
    await nextTick()
    const canProceed = wrapper.emitted('can-proceed')
    expect(canProceed[canProceed.length - 1]).toEqual([true])
  })
})


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
    wsHandlers['setup:tool_connected']({ tool_name: 'mcp_connected' })
    await nextTick()
    const stepData = wrapper.emitted('step-data')
    const latest = stepData[stepData.length - 1][0].connectedTools
    expect(latest).toContain('claude_code')
    expect(latest).not.toContain('codex_cli')
  })

  it('advance label is "Next tool" mid-walk and "Install agents & skills" on the last tool', async () => {
    const wrapper = await mountStep(['claude_code', 'codex_cli'], 'saas')
    wsHandlers['setup:tool_connected']({ tool_name: 'mcp_connected' })
    await nextTick()
    expect(wrapper.find('[data-testid="hero-advance"]').text()).toContain('Next tool')
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


describe('SetupStep2Connect — per-tool fallback isolation (walk)', () => {
  it('toggling the fallback on one tool does not carry to the next tool', async () => {
    const wrapper = await mountStep(['claude_code', 'codex_cli'], 'saas')
    await wrapper.find('[data-testid="fallback-toggle"]').trigger('click')
    await nextTick()
    expect(wrapper.text()).toContain('Generate API Key')
    wsHandlers['setup:tool_connected']({ tool_name: 'mcp_connected' })
    await nextTick()
    await wrapper.find('[data-testid="hero-advance"]').trigger('click')
    await nextTick()
    expect(wrapper.find('.connect-eyebrow').text()).toContain('TOOL 2 OF 2')
    expect(wrapper.text()).toContain('Use an API key instead')
    expect(wrapper.text()).not.toContain('Generate API Key')
  })
})


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
    expect(text).not.toContain('root CA')
    expect(text).not.toContain('mkcert')
  })
})


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

  it('SaaS + HTTPS: oauth-cert-note renders when ssl_enabled', async () => {
    const wrapper = await mountStepSsl(['claude_code'], true)
    expect(wrapper.find('[data-testid="oauth-cert-note"]').exists()).toBe(true)
  })
})


describe('SetupStep2Connect — OpenCode snippet syntax + client labels (FE-9383)', () => {
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
