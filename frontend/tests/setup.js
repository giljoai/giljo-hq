import { config } from '@vue/test-utils'
import { vi } from 'vitest'
import { createVuetify } from 'vuetify'
import { createPinia } from 'pinia'
import { unresolvedAssetGuard } from './helpers/unresolvedAssetGuard.js'
import { routerInjectionGuard } from './helpers/routerInjectionGuard.js'
import { draggable } from '@/directives/draggable'

// Define global Vuetify component mocks (PascalCase for vi.mock)
const VuetifyMock = {
  VApp: { template: '<div class="v-app"><slot /></div>' },
  VMain: { template: '<div class="v-main"><slot /></div>' },
  VAppBar: { template: '<div class="v-app-bar"><slot /></div>' },
  VContainer: { template: '<div><slot /></div>' },
  VRow: { template: '<div><slot /></div>' },
  VCol: { template: '<div><slot /></div>' },
  VCard: { template: '<div><slot /></div>' },
  VCardTitle: { template: '<div><slot /></div>' },
  VCardText: { template: '<div><slot /></div>' },
  VCardActions: { template: '<div><slot /></div>' },
  VBtn: { template: '<button v-bind="$attrs"><slot /></button>' },
  VIcon: { template: '<span class="v-icon"><slot /></span>' },
  VImg: { template: '<div class="v-img"><slot /></div>' },
  VAvatar: { template: '<div class="v-avatar"><slot /></div>' },
  VTooltip: { template: '<div class="v-tooltip"><slot /></div>' },
  VDialog: { template: '<div class="v-dialog"><slot /></div>' },
  // NOTE (FE-9553): default slot ONLY. Anything in a scoped `activator` slot
  // does not render, so assertions about it pass vacuously — stub v-menu
  // locally when you need the activator. See the useToast blind-spot note.
  VMenu: { template: '<div class="v-menu"><slot /></div>' },
  VList: { template: '<div class="v-list"><slot /></div>' },
  VListItem: { template: '<div class="v-list-item"><slot /></div>' },
  VListItemTitle: { template: '<div class="v-list-item-title"><slot /></div>' },
  VExpansionPanels: { template: '<div class="v-expansion-panels"><slot /></div>' },
  VExpansionPanel: { template: '<div class="v-expansion-panel"><slot /></div>' },
  VExpansionPanelTitle: { template: '<div class="v-expansion-panel-title"><slot /></div>' },
  VExpansionPanelText: { template: '<div class="v-expansion-panel-text"><slot /></div>' },
  VTextField: { template: '<input class="v-text-field" v-bind="$attrs" />' },
  VTextarea: { template: '<textarea class="v-textarea" v-bind="$attrs"></textarea>' },
  VSelect: { template: '<div class="v-select" v-bind="$attrs"><slot /></div>' },
  VAutocomplete: { template: '<div class="v-autocomplete" v-bind="$attrs"><slot /></div>' },
  VCombobox: { template: '<div class="v-combobox" v-bind="$attrs"><slot /></div>' },
  VCheckbox: { template: '<input type="checkbox" class="v-checkbox" v-bind="$attrs" />' },
  VSwitch: { template: '<input type="checkbox" class="v-switch" v-bind="$attrs" />' },
  VRadio: { template: '<input type="radio" class="v-radio" v-bind="$attrs" />' },
  VRadioGroup: { template: '<div class="v-radio-group"><slot /></div>' },
  VSlider: { template: '<div class="v-slider" v-bind="$attrs"><slot /></div>' },
  VRangeSlider: { template: '<div class="v-range-slider" v-bind="$attrs"><slot /></div>' },
  VFileInput: { template: '<input type="file" class="v-file-input" v-bind="$attrs" />' },
  VColorPicker: { template: '<div class="v-color-picker" v-bind="$attrs"><slot /></div>' },
  VForm: { template: '<form class="v-form"><slot /></form>' },
  VTabs: { template: '<div class="v-tabs"><slot /></div>' },
  VTab: { template: '<div class="v-tab"><slot /></div>' },
  VTabItem: { template: '<div class="v-tab-item"><slot /></div>' },
  VWindow: { template: '<div class="v-window"><slot /></div>' },
  VWindowItem: { template: '<div class="v-window-item"><slot /></div>' },
  VNavigationDrawer: { template: '<div class="v-navigation-drawer"><slot /></div>' },
  VToolbar: { template: '<div class="v-toolbar"><slot /></div>' },
  VToolbarTitle: { template: '<div class="v-toolbar-title"><slot /></div>' },
  VToolbarItems: { template: '<div class="v-toolbar-items"><slot /></div>' },
  VDataTable: { template: '<div class="v-data-table"><slot /></div>' },
  VDataTableServer: { template: '<div class="v-data-table-server"><slot /></div>' },
  VStepper: { template: '<div class="v-stepper"><slot /></div>' },
  VStepperHeader: { template: '<div class="v-stepper-header"><slot /></div>' },
  VStepperItem: { template: '<div class="v-stepper-item"><slot /></div>' },
  VStepperContent: { template: '<div class="v-stepper-content"><slot /></div>' },
  VStepperStep: { template: '<div class="v-stepper-step"><slot /></div>' },
  VStepperWindowItem: { template: '<div class="v-stepper-window-item"><slot /></div>' },
  VDivider: { template: '<hr class="v-divider" />' },
  VSpacer: { template: '<div class="v-spacer"></div>' },
  VProgressLinear: { template: '<div class="v-progress-linear"><slot /></div>' },
  VProgressCircular: { template: '<div class="v-progress-circular">Progress</div>' },
  VSnackbar: { template: '<div class="v-snackbar"><slot /></div>' },
  VAlert: { template: '<div class="v-alert"><slot /></div>' },
  VBadge: { template: '<span class="v-badge"><slot /></span>' },
  VChip: { template: '<span class="v-chip"><slot /></span>' },
  VChipGroup: { template: '<div class="v-chip-group"><slot /></div>' },
  VOverlay: { template: '<div class="v-overlay"><slot /></div>' },
  VBanner: { template: '<div class="v-banner"><slot /></div>' },
  VBreadcrumbs: { template: '<div class="v-breadcrumbs"><slot /></div>' },
  VBreadcrumbsItem: { template: '<div class="v-breadcrumbs-item"><slot /></div>' },
  VPagination: { template: '<div class="v-pagination"><slot /></div>' },
}

// Global CSS and component mocking
vi.mock('vuetify/components', () => VuetifyMock)

// Mock all CSS imports
vi.mock('**/*.css', () => ({
  __esModule: true,
  default: ''
}))

// Stub out Vuetify plugin and composables
vi.mock('vuetify', () => ({
  createVuetify: () => ({
    install: () => {}
  }),
  useDisplay: () => ({
    mobile: { value: false },
    xs: { value: false },
    sm: { value: false },
    md: { value: false },
    lg: { value: true },
    xl: { value: false },
    xxl: { value: false },
    // Compound breakpoint refs added for FE-6050 (smAndDown used in ProjectsTable.vue)
    smAndDown: { value: false },
    smAndUp: { value: true },
    mdAndDown: { value: false },
    mdAndUp: { value: true },
    lgAndDown: { value: false },
    lgAndUp: { value: true },
    xlAndDown: { value: false },
    xlAndUp: { value: true },
    width: { value: 1920 },
    height: { value: 1080 },
    platform: { value: { android: false, ios: false, mac: false, touch: false, ssr: false } },
    name: { value: 'lg' }
  }),
  useTheme: () => ({
    global: {
      name: { value: 'dark' },
      current: { value: { dark: true, colors: { background: '#121212' } } }
    },
    name: { value: 'dark' },
    current: { value: { dark: true, colors: { background: '#121212' } } },
    computedThemes: { value: {} },
    themes: { value: {} },
    isDisabled: { value: false },
    change: vi.fn()
  })
}))

// Globally stub Vuetify components (kebab-case for template resolution)
//
// FE-9366: this stub renders ONLY the default slot. A component's named/scoped
// slots (VSelect's #item / #selection, VList's #prepend / #append, ...) never
// execute against this stub, so a bug living in one of those slots can ship
// behind a fully green suite (FE-9365d — the `??` dropdown defect). Before you
// add a test that reads a value out of a scoped slot on any component stubbed
// below, use `withRealVuetify()` from tests/helpers/realVuetify.js instead of
// asserting through this flat stub — see that file's header comment for why
// `stubs: { VSelect: false }` alone does not work as an escape hatch.
//
// FE-9397: this map is not a convenience — it IS component resolution for this
// tier. Nothing registers Vuetify's real components (the `vuetify` module is
// mocked above), so a tag absent from this map does not resolve at all and
// renders as an inert unknown element instead. That used to be a console
// warning nobody read; it is now a test failure, enforced by the guard wired at
// the bottom of this file. Adding a Vuetify tag to a template means adding it
// here too.
config.global.stubs = {
  'v-app': { template: '<div class="v-app"><slot /></div>' },
  'v-main': { template: '<div class="v-main"><slot /></div>' },
  'v-app-bar': { template: '<div class="v-app-bar"><slot /></div>' },
  'v-container': { template: '<div><slot /></div>' },
  'v-row': { template: '<div><slot /></div>' },
  'v-col': { template: '<div><slot /></div>' },
  'v-card': { template: '<div><slot /></div>' },
  'v-card-title': { template: '<div><slot /></div>' },
  'v-card-text': { template: '<div><slot /></div>' },
  'v-card-actions': { template: '<div><slot /></div>' },
  'v-sheet': { template: '<div class="v-sheet"><slot /></div>' },
  'v-btn': { template: '<button class="v-btn" v-bind="$attrs"><slot /></button>' },
  'v-btn-toggle': { template: '<div class="v-btn-toggle" v-bind="$attrs"><slot /></div>' },
  'v-icon': { template: '<span class="v-icon"><slot /></span>' },
  'v-img': { template: '<div class="v-img"><slot /></div>' },
  'v-avatar': { template: '<div class="v-avatar"><slot /></div>' },
  'v-tooltip': { template: '<div class="v-tooltip"><slot /></div>' },
  'v-dialog': { template: '<div class="v-dialog"><slot /></div>' },
  // NOTE (FE-9553): default slot ONLY. Anything in a scoped `activator` slot
  // does not render, so assertions about it pass vacuously — stub v-menu
  // locally when you need the activator. See the useToast blind-spot note.
  'v-menu': { template: '<div class="v-menu"><slot /></div>' },
  'v-list': { template: '<div class="v-list"><slot /></div>' },
  'v-list-item': { template: '<div class="v-list-item"><slot /></div>' },
  'v-list-item-title': { template: '<div class="v-list-item-title"><slot /></div>' },
  'v-list-item-subtitle': { template: '<div class="v-list-item-subtitle"><slot /></div>' },
  'v-list-subheader': { template: '<div class="v-list-subheader"><slot /></div>' },
  'v-expansion-panels': { template: '<div class="v-expansion-panels"><slot /></div>' },
  'v-expansion-panel': { template: '<div class="v-expansion-panel"><slot /></div>' },
  'v-expansion-panel-title': { template: '<div class="v-expansion-panel-title"><slot /></div>' },
  'v-expansion-panel-text': { template: '<div class="v-expansion-panel-text"><slot /></div>' },
  'v-text-field': { template: '<input class="v-text-field" v-bind="$attrs" />' },
  'v-textarea': { template: '<textarea class="v-textarea" v-bind="$attrs"></textarea>' },
  'v-select': { template: '<div class="v-select" v-bind="$attrs"><slot /></div>' },
  'v-autocomplete': { template: '<div class="v-autocomplete" v-bind="$attrs"><slot /></div>' },
  'v-combobox': { template: '<div class="v-combobox" v-bind="$attrs"><slot /></div>' },
  'v-checkbox': { template: '<input type="checkbox" class="v-checkbox" v-bind="$attrs" />' },
  'v-checkbox-btn': { template: '<input type="checkbox" class="v-checkbox-btn" v-bind="$attrs" />' },
  'v-switch': { template: '<input type="checkbox" class="v-switch" v-bind="$attrs" />' },
  'v-radio': { template: '<input type="radio" class="v-radio" v-bind="$attrs" />' },
  'v-radio-group': { template: '<div class="v-radio-group"><slot /></div>' },
  'v-slider': { template: '<div class="v-slider" v-bind="$attrs"><slot /></div>' },
  'v-range-slider': { template: '<div class="v-range-slider" v-bind="$attrs"><slot /></div>' },
  'v-file-input': { template: '<input type="file" class="v-file-input" v-bind="$attrs" />' },
  'v-color-picker': { template: '<div class="v-color-picker" v-bind="$attrs"><slot /></div>' },
  // Real VDatePicker builds its calendar entirely from props and has no default
  // slot, so this flat stub renders no dates. It is the one component in this
  // map where the stub genuinely shows nothing a user would see -- assert on
  // the emitted `update:model-value`, not on rendered days.
  'v-date-picker': { template: '<div class="v-date-picker" v-bind="$attrs"></div>' },
  'v-form': { template: '<form class="v-form"><slot /></form>' },
  'v-tabs': { template: '<div class="v-tabs"><slot /></div>' },
  'v-tab': { template: '<div class="v-tab"><slot /></div>' },
  'v-tab-item': { template: '<div class="v-tab-item"><slot /></div>' },
  'v-window': { template: '<div class="v-window"><slot /></div>' },
  'v-window-item': { template: '<div class="v-window-item"><slot /></div>' },
  'v-expand-transition': { template: '<div class="v-expand-transition"><slot /></div>' },
  'v-navigation-drawer': { template: '<div class="v-navigation-drawer"><slot /></div>' },
  'v-toolbar': { template: '<div class="v-toolbar"><slot /></div>' },
  'v-toolbar-title': { template: '<div class="v-toolbar-title"><slot /></div>' },
  'v-toolbar-items': { template: '<div class="v-toolbar-items"><slot /></div>' },
  'v-data-table': { template: '<div class="v-data-table"><slot /></div>' },
  'v-data-table-server': { template: '<div class="v-data-table-server"><slot /></div>' },
  'v-stepper': { template: '<div class="v-stepper"><slot /></div>' },
  'v-stepper-header': { template: '<div class="v-stepper-header"><slot /></div>' },
  'v-stepper-item': { template: '<div class="v-stepper-item"><slot /></div>' },
  'v-stepper-content': { template: '<div class="v-stepper-content"><slot /></div>' },
  'v-stepper-step': { template: '<div class="v-stepper-step"><slot /></div>' },
  'v-stepper-window-item': { template: '<div class="v-stepper-window-item"><slot /></div>' },
  'v-divider': { template: '<hr class="v-divider" />' },
  'v-spacer': { template: '<div class="v-spacer"></div>' },
  'v-progress-linear': { template: '<div class="v-progress-linear"><slot /></div>' },
  'v-progress-circular': { template: '<div class="v-progress-circular">Progress</div>' },
  'v-snackbar': { template: '<div class="v-snackbar"><slot /></div>' },
  'v-alert': { template: '<div class="v-alert"><slot /></div>' },
  'v-badge': { template: '<span class="v-badge"><slot /></span>' },
  'v-chip': { template: '<span class="v-chip"><slot /></span>' },
  'v-chip-group': { template: '<div class="v-chip-group"><slot /></div>' },
  'v-overlay': { template: '<div class="v-overlay"><slot /></div>' },
  'v-banner': { template: '<div class="v-banner"><slot /></div>' },
  'v-breadcrumbs': { template: '<div class="v-breadcrumbs"><slot /></div>' },
  'v-breadcrumbs-item': { template: '<div class="v-breadcrumbs-item"><slot /></div>' },
  'v-pagination': { template: '<div class="v-pagination"><slot /></div>' },
  // Not Vuetify, but resolved the same way and previously just as silent
  // (FE-9397 measured 51 unresolved `router-link` renders across 3 specs).
  // Specs here mock the `vue-router` MODULE rather than installing a router, so
  // nothing registers this component. Rendering a real anchor with an href
  // keeps link-target assertions meaningful; reading `to` off a dead unknown
  // element, which is what they were doing, does not.
  'router-link': {
    props: ['to'],
    template:
      '<a class="router-link" :href="typeof to === \'string\' ? to : (to && to.path) || undefined"><slot /></a>',
  },
}

// Globally register the app's custom directives.
//
// FE-9403: `v-draggable` is a real product directive — src/main.js:105 registers
// it and it makes every dialog draggable. Nothing registered it in this tier, so
// it failed to resolve in 56 spec files and simply never ran, reported only as a
// console warning. Unlike an unresolved component (FE-9397), an unresolved
// directive leaves no residue at all: no inert element, no surviving class, no
// slot children. There is nothing in the DOM for an assertion to catch, which is
// what made it the quieter half of the same hole.
//
// The REAL directive is registered here, not a stub of it, so this tier cannot
// drift from what main.js installs. Measured on the way in: it now mounts and
// runs to completion 1314 times across the suite, every time via the `.dlg-header`
// handle that BaseDialog supplies (never the `.v-card-title` fallback, which the
// flat stub above renders without its class). Adding a directive to main.js means
// adding it here too.
config.global.directives = {
  ...config.global.directives,
  draggable,
}

// Create a minimal Vuetify mock plugin
const vuetify = createVuetify()

// Create Pinia instance for testing
const pinia = createPinia()

// Global mocks and stubs
config.global.plugins = [vuetify, pinia]

// Provide mock implementations for browser APIs
Object.defineProperty(window, 'localStorage', {
  value: {
    getItem: vi.fn(),
    setItem: vi.fn(),
    removeItem: vi.fn(),
    clear: vi.fn()
  },
  writable: true
})

// Mock Web APIs
window.matchMedia = vi.fn().mockImplementation(query => ({
  matches: false,
  media: query,
  onchange: null,
  addListener: vi.fn(),
  removeListener: vi.fn(),
  addEventListener: vi.fn(),
  removeEventListener: vi.fn()
}))

// Mock document.execCommand for clipboard operations
document.execCommand = vi.fn(() => true)

// FE-9366: jsdom implements neither of these, and Vuetify's real VOverlay
// (location strategies) and VVirtualScroll (used inside a real VList) reach
// for them unconditionally on mount. They are otherwise silent under the
// flat component stubs (this file's `config.global.stubs`, above) because a
// stub never mounts Vuetify's real overlay/virtual-scroll internals to begin
// with -- but `withRealVuetify()` (tests/helpers/realVuetify.js) opts a mount
// into the real components, and without these two the menu-open path throws
// "ResizeObserver is not defined" / "visualViewport is not defined" instead
// of rendering. Defined globally (not scoped to the helper) because any
// future real-Vuetify mount needs them, not just this one.
if (typeof window.ResizeObserver === 'undefined') {
  window.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
}
if (typeof window.visualViewport === 'undefined') {
  window.visualViewport = {
    width: window.innerWidth,
    height: window.innerHeight,
    offsetLeft: 0,
    offsetTop: 0,
    scale: 1,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }
}

// Mock API service with comprehensive namespace coverage
// NOTE: The full API object must be inside the vi.mock factory because vi.mock is hoisted.
// Both named export `api` and default export must point to the same object
// because stores use both: `import api from` (default) and `import { api } from` (named).
vi.mock('@/services/api', () => {
  const apiObj = {
    get: vi.fn(() => Promise.resolve({ data: {} })),
    post: vi.fn(() => Promise.resolve({ data: { success: true } })),
    put: vi.fn(() => Promise.resolve({ data: { success: true } })),
    delete: vi.fn(() => Promise.resolve({ data: { success: true } })),
    auth: {
      login: vi.fn(() => Promise.resolve({ data: { user: {}, token: 'mock-token' } })),
      logout: vi.fn(() => Promise.resolve({ data: { success: true } })),
      me: vi.fn(() => Promise.resolve({ data: { id: 1, username: 'testuser', role: 'admin' } })),
      register: vi.fn(() => Promise.resolve({ data: { success: true } })),
      createFirstAdmin: vi.fn(() => Promise.resolve({ data: { success: true } })),
      listUsers: vi.fn(() => Promise.resolve({ data: [] })),
      updateUser: vi.fn(() => Promise.resolve({ data: { success: true } })),
      checkFirstLogin: vi.fn(() => Promise.resolve({ data: { is_first_login: false } })),
      completeFirstLogin: vi.fn(() => Promise.resolve({ data: { success: true } })),
      verifyPinAndResetPassword: vi.fn(() => Promise.resolve({ data: { success: true } })),
      setRecoveryPin: vi.fn(() => Promise.resolve({ data: { success: true } })),
      resetUserPassword: vi.fn(() => Promise.resolve({ data: { success: true } })),
    },
    prompts: {
      staging: vi.fn(() => Promise.resolve({ data: { prompt: 'Mock staging prompt' } })),
      execution: vi.fn(() => Promise.resolve({ data: { prompt: 'Mock orchestrator prompt' } })),
      agentPrompt: vi.fn(() => Promise.resolve({ data: { prompt: 'Mock agent prompt' } })),
      implementation: vi.fn(() => Promise.resolve({ data: { prompt: 'Mock implementation prompt', agent_count: 3 } })),
      orchestrator: vi.fn(() => Promise.resolve({ data: { prompt: 'Mock orchestrator prompt' } })),
      // FE-6165f: chain (run-scoped) kickoff prompts — BE-6165d ChainPromptResponse shape.
      chainStaging: vi.fn(() =>
        Promise.resolve({
          data: {
            run_id: 'run-mock',
            head_project_id: 'proj-head',
            orchestrator_job_id: 'job-mock',
            prompt: 'Mock chain staging prompt',
          },
        }),
      ),
      chainImplementation: vi.fn(() =>
        Promise.resolve({
          data: {
            run_id: 'run-mock',
            head_project_id: 'proj-head',
            orchestrator_job_id: 'job-mock',
            prompt: 'Mock chain implementation prompt',
          },
        }),
      ),
      // FE-9629: one chain MEMBER's own orchestrator bootstrap (project-scoped).
      chainMember: vi.fn(() =>
        Promise.resolve({
          data: {
            run_id: 'run-mock',
            project_id: 'proj-member',
            orchestrator_job_id: 'job-member',
            prompt: 'Mock chain member prompt',
          },
        }),
      ),
    },
    templates: {
      list: vi.fn(() => Promise.resolve({ data: [] })),
      get: vi.fn(() => Promise.resolve({ data: {} })),
      create: vi.fn(() => Promise.resolve({ data: {} })),
      update: vi.fn(() => Promise.resolve({ data: {} })),
      delete: vi.fn(() => Promise.resolve({ data: { success: true } })),
      history: vi.fn(() => Promise.resolve({ data: [] })),
      restore: vi.fn(() => Promise.resolve({ data: { success: true } })),
      preview: vi.fn(() => Promise.resolve({ data: {} })),
      reset: vi.fn(() => Promise.resolve({ data: { success: true } })),
      activeCount: vi.fn(() => Promise.resolve({ data: { count: 0 } })),
      cloneToProduct: vi.fn(() => Promise.resolve({ data: { success: true } })),
    },
    projects: {
      list: vi.fn(() => Promise.resolve({ data: [] })),
      get: vi.fn(() => Promise.resolve({ data: {} })),
      getOrchestrator: vi.fn(() => Promise.resolve({ data: {} })),
      getActive: vi.fn(() => Promise.resolve({ data: [] })),
      create: vi.fn(() => Promise.resolve({ data: {} })),
      update: vi.fn(() => Promise.resolve({ data: {} })),
      delete: vi.fn(() => Promise.resolve({ data: { success: true } })),
      fetchDeleted: vi.fn(() => Promise.resolve({ data: [] })),
      getNextSeries: vi.fn(() => Promise.resolve({ data: {} })),
      getAvailableSeries: vi.fn(() => Promise.resolve({ data: [] })),
      checkSeries: vi.fn(() => Promise.resolve({ data: {} })),
      usedSubseries: vi.fn(() => Promise.resolve({ data: [] })),
      activate: vi.fn(() => Promise.resolve({ data: { success: true } })),
      deactivate: vi.fn(() => Promise.resolve({ data: { success: true } })),
      complete: vi.fn(() => Promise.resolve({ data: { success: true } })),
      cancel: vi.fn(() => Promise.resolve({ data: { success: true } })),
      restore: vi.fn(() => Promise.resolve({ data: { success: true } })),
      purgeDeleted: vi.fn(() => Promise.resolve({ data: { success: true } })),
      purgeAllDeleted: vi.fn(() => Promise.resolve({ data: { success: true } })),
      restoreCompleted: vi.fn(() => Promise.resolve({ data: { success: true } })),
      cancelStaging: vi.fn(() => Promise.resolve({ data: { success: true } })),
      completeWithData: vi.fn(() => Promise.resolve({ data: { success: true } })),
      archive: vi.fn(() => Promise.resolve({ data: { success: true } })),
      launchImplementation: vi.fn(() => Promise.resolve({ data: { success: true } })),
      // FE-6165f: chain resume re-stages a failed project through the sacred gate.
      restage: vi.fn(() => Promise.resolve({ data: { success: true } })),
    },
    products: {
      list: vi.fn(() => Promise.resolve({ data: [] })),
      get: vi.fn(() => Promise.resolve({ data: {} })),
      // FE-9529: renamed from getActive -- resolves the DEFAULT product
      // (is_default), not is_active.
      getDefault: vi.fn(() => Promise.resolve({ data: [] })),
      setDefault: vi.fn(() => Promise.resolve({ data: {} })),
      create: vi.fn(() => Promise.resolve({ data: {} })),
      update: vi.fn(() => Promise.resolve({ data: {} })),
      delete: vi.fn(() => Promise.resolve({ data: { success: true } })),
      getCascadeImpact: vi.fn(() => Promise.resolve({ data: {} })),
      activate: vi.fn(() => Promise.resolve({ data: { success: true } })),
      deactivate: vi.fn(() => Promise.resolve({ data: { success: true } })),
      getDeletedProducts: vi.fn(() => Promise.resolve({ data: [] })),
      restoreProduct: vi.fn(() => Promise.resolve({ data: { success: true } })),
      getMemoryEntries: vi.fn(() => Promise.resolve({ data: [] })),
    },
    taxonomyTypes: {
      list: vi.fn(() => Promise.resolve({ data: [] })),
      create: vi.fn(() => Promise.resolve({ data: {} })),
      update: vi.fn(() => Promise.resolve({ data: {} })),
      delete: vi.fn(() => Promise.resolve({ data: { success: true } })),
    },
    projectStatuses: {
      list: vi.fn(() => Promise.resolve({ data: [] })),
    },
    tasks: {
      list: vi.fn(() => Promise.resolve({ data: [] })),
      get: vi.fn(() => Promise.resolve({ data: {} })),
      create: vi.fn(() => Promise.resolve({ data: {} })),
      update: vi.fn(() => Promise.resolve({ data: {} })),
      delete: vi.fn(() => Promise.resolve({ data: { success: true } })),
      changeStatus: vi.fn(() => Promise.resolve({ data: { success: true } })),
      summary: vi.fn(() => Promise.resolve({ data: {} })),
      convertToProject: vi.fn(() => Promise.resolve({ data: { success: true } })),
    },
    agentJobs: {
      list: vi.fn(() => Promise.resolve({ data: [] })),
      get: vi.fn(() => Promise.resolve({ data: {} })),
      spawn: vi.fn(() => Promise.resolve({ data: {} })),
      status: vi.fn(() => Promise.resolve({ data: {} })),
      updateMission: vi.fn(() => Promise.resolve({ data: { success: true } })),
      messages: vi.fn(() => Promise.resolve({ data: [] })),
    },
    users: {
      update: vi.fn(() => Promise.resolve({ data: {} })),
      getFieldToggleConfig: vi.fn(() => Promise.resolve({ data: {} })),
    },
    // Threads — Agent Message Hub (FE-6054e). BE-9012d: retires the bus's
    // `messages` namespace (`/api/v1/messages/*`) entirely; any UI code
    // posting to "a" project/conductor thread now goes through this namespace
    // (usually via commHubStore, not called directly). Defaults are inert
    // empty results — tests that care override per-call with mockResolvedValueOnce.
    threads: {
      list: vi.fn(() => Promise.resolve({ data: { threads: [] } })),
      myTurn: vi.fn(() => Promise.resolve({ data: { threads: [] } })),
      search: vi.fn(() => Promise.resolve({ data: { threads: [] } })),
      history: vi.fn(() => Promise.resolve({ data: { thread: null, messages: [] } })),
      // FE-9586: selectThread persists the operator's read watermark, so every
      // spec that opens a thread reaches this — including specs that never mention it.
      markRead: vi.fn(() => Promise.resolve({ data: {} })),
      // FE-9586: the banner family's read. Empty is the quiet default.
      attention: vi.fn(() => Promise.resolve({ data: { mentions: [], directed_action: [] } })),
      participants: vi.fn(() => Promise.resolve({ data: { participants: [] } })),
      create: vi.fn(() => Promise.resolve({ data: {} })),
      post: vi.fn(() => Promise.resolve({ data: { message_id: 'mock-message-id' } })),
      passBaton: vi.fn(() => Promise.resolve({ data: {} })),
      delete: vi.fn(() => Promise.resolve({ data: { success: true } })),
      getDeleted: vi.fn(() => Promise.resolve({ data: { threads: [] } })),
      restore: vi.fn(() => Promise.resolve({ data: {} })),
    },
    settings: {
      get: vi.fn(() => Promise.resolve({ data: {} })),
      getAgentSilenceThreshold: vi.fn(() =>
        Promise.resolve({ data: { agent_silence_threshold_minutes: 10 } }),
      ),
      updateAgentSilenceThreshold: vi.fn(() =>
        Promise.resolve({ data: { agent_silence_threshold_minutes: 10 } }),
      ),
      getDatabase: vi.fn(() => Promise.resolve({ data: {} })),
      testDatabase: vi.fn(() => Promise.resolve({ data: { success: true, message: 'Connected' } })),
      getCookieDomains: vi.fn(() => Promise.resolve({ data: [] })),
      addCookieDomain: vi.fn(() => Promise.resolve({ data: { success: true } })),
      removeCookieDomain: vi.fn(() => Promise.resolve({ data: { success: true } })),
    },
    health: {
      check: vi.fn(() => Promise.resolve({ data: { status: 'healthy' } })),
    },
    setup: {
      status: vi.fn(() => Promise.resolve({ data: { is_fresh_install: false, is_configured: true } })),
    },
    apiKeys: {
      list: vi.fn(() => Promise.resolve({ data: [] })),
      getActive: vi.fn(() => Promise.resolve({ data: [] })),
      create: vi.fn(() => Promise.resolve({ data: {} })),
      delete: vi.fn(() => Promise.resolve({ data: { success: true } })),
    },
    // FE-9274 / FE-9569: durable connect-credential status (Connect surface +
    // the setup wizard's Connect step). Default = nothing connected yet.
    connect: {
      credentialStatus: vi.fn(() =>
        Promise.resolve({
          data: {
            has_valid_api_key: false,
            has_valid_oauth: false,
            has_expired_oauth: false,
            connected_harnesses: {},
          },
        }),
      ),
    },
    orchestrator: {
      launchProject: vi.fn(() => Promise.resolve({ data: { success: true } })),
    },
    organizations: {
      list: vi.fn(() => Promise.resolve({ data: [] })),
      get: vi.fn(() => Promise.resolve({ data: {} })),
      create: vi.fn(() => Promise.resolve({ data: {} })),
      update: vi.fn(() => Promise.resolve({ data: {} })),
      delete: vi.fn(() => Promise.resolve({ data: { success: true } })),
      listMembers: vi.fn(() => Promise.resolve({ data: [] })),
      inviteMember: vi.fn(() => Promise.resolve({ data: { success: true } })),
      changeMemberRole: vi.fn(() => Promise.resolve({ data: { success: true } })),
      removeMember: vi.fn(() => Promise.resolve({ data: { success: true } })),
      transferOwnership: vi.fn(() => Promise.resolve({ data: { success: true } })),
    },
    visionDocuments: {
      listByProduct: vi.fn(() => Promise.resolve({ data: [] })),
      upload: vi.fn(() => Promise.resolve({ data: {} })),
      delete: vi.fn(() => Promise.resolve({ data: { success: true } })),
    },
    git: {
      getSettings: vi.fn(() => Promise.resolve({ data: {} })),
      toggle: vi.fn(() => Promise.resolve({ data: { success: true } })),
    },
    downloads: {
      generateSlashCommandsInstructions: vi.fn(() => Promise.resolve({ data: {} })),
    },
    system: {
      getOrchestratorPrompt: vi.fn(() => Promise.resolve({ data: {} })),
      updateOrchestratorPrompt: vi.fn(() => Promise.resolve({ data: { success: true } })),
      resetOrchestratorPrompt: vi.fn(() => Promise.resolve({ data: { success: true } })),
    },
    stats: {
      getCallCounts: vi.fn(() => Promise.resolve({ data: {} })),
    },
    approvals: {
      listPending: vi.fn(() => Promise.resolve({ data: { items: [], count: 0 } })),
      decide: vi.fn(() => Promise.resolve({ data: { approval_id: 'mock-id', status: 'decided', decided_option_id: 'opt', job_id: 'job', project_id: 'proj' } })),
    },
    notifications: {
      list: vi.fn(() => Promise.resolve({ data: [] })),
      markRead: vi.fn(() => Promise.resolve({ data: {} })),
      markDismissed: vi.fn(() => Promise.resolve({ data: {} })),
    },
    // FE-6022b: roadmap REST (used by RoadmapView + the sequence runner's
    // default-order resolution).
    roadmap: {
      get: vi.fn(() => Promise.resolve({ data: { product_id: 'prod', roadmap: null, items: [] } })),
      reorder: vi.fn(() => Promise.resolve({ data: { success: true } })),
      removeItem: vi.fn(() => Promise.resolve({ data: { success: true } })),
    },
    // FE-6131e: sequence-runs REST (BE-6131a durable run record).
    sequenceRuns: {
      create: vi.fn(() => Promise.resolve({ data: { id: 'run-mock', project_ids: [], resolved_order: [], project_statuses: {} } })),
      get: vi.fn(() => Promise.resolve({ data: { id: 'run-mock', project_ids: [], resolved_order: [], project_statuses: {} } })),
      update: vi.fn(() => Promise.resolve({ data: { id: 'run-mock', project_ids: [], resolved_order: [], project_statuses: {} } })),
      // FE-6165e: list returns a BARE ARRAY of serialized runs (NOT wrapped).
      list: vi.fn(() => Promise.resolve({ data: [] })),
      // FE-6165e: release a run. mode = 'graceful' (-> terminated) | 'cancel' (-> cancelled).
      release: vi.fn(() => Promise.resolve({ data: { id: 'run-mock', status: 'cancelled' } })),
      // FE-6171b: granular member removal (Editing tier).
      removeMember: vi.fn(() => Promise.resolve({ data: { success: true } })),
      // FE-6178: deactivate the whole chain (members -> inactive, run -> cancelled).
      deactivate: vi.fn(() => Promise.resolve({ data: { id: 'run-mock', status: 'cancelled' } })),
      // FE-9632: stop a RUNNING chain (run -> cancelled, member underway terminated
      // with its agent history kept, unreached members -> inactive).
      stop: vi.fn(() => Promise.resolve({ data: { id: 'run-mock', status: 'cancelled' } })),
      // BE-9098: durable per-member review ack (returns the updated run).
      markReviewed: vi.fn(() =>
        Promise.resolve({ data: { id: 'run-mock', project_ids: [], resolved_order: [], reviewed_project_ids: [] } }),
      ),
    },
  }
  return {
    api: apiObj,
    default: apiObj,
    // apiClient is the raw axios instance real services import directly
    // (e.g. saas/services/account.js). Mirror it onto the mock so those
    // modules resolve a working get/post/... under the global mock.
    apiClient: apiObj,
    // dedupedRequest (FE-6059) is imported by real services; the global mock
    // must provide it or the import resolves undefined and the call throws an
    // unhandled rejection that races vitest worker teardown under CI's
    // parallelism. Passthrough: just run the underlying request fn.
    dedupedRequest: (_key, requestFn) => Promise.resolve().then(requestFn),
    __resetRequestDedupe: vi.fn(),
    setTenantKey: vi.fn(),
    updateApiBaseURL: vi.fn(),
    parseErrorResponse: vi.fn(() => ({ message: 'Mock error', isStructured: false })),
    getErrorMessage: vi.fn(() => 'Mock error message'),
  }
})

// Mock WebSocket service
vi.mock('@/services/websocket', () => ({
  webSocketService: {
    on: vi.fn(),
    off: vi.fn(),
    send: vi.fn(),
    isConnected: false
  }
}))

// Mock useToast composable
//
// KNOWN TEST BLIND SPOT (FE-9553) — read before writing a toast assertion.
//
// The factory returns a FRESH vi.fn() on every useToast() call, so the spy the
// code under test calls is never the spy your test can see. A spec that asserts
// through this global mock is therefore asserting on an object nothing touched:
// `expect(showToast).not.toHaveBeenCalled()` passes whether or not the code
// toasts, and `toHaveBeenCalled()` can never pass at all. Any gate added inside
// useToast.js is likewise invisible to the entire suite.
//
// To assert on toasts, mock the module LOCALLY in your spec with a hoisted
// shared spy — `vi.hoisted(() => vi.fn())` — the way
// src/composables/useHubNotifications.spec.js and
// tests/stores/websocket.spec.js do. Deliberately NOT removed here: several
// hundred specs rely on toasts being harmlessly stubbed, and unmocking globally
// is its own project.
//
// The same shape recurs elsewhere, so treat it as a pattern rather
// than a quirk of this mock:
//   1. tests/stores/websocket.spec.js mocked the notification store the same
//      way, so no test could observe a bell row being written. Fixed there with
//      a hoisted shared spy.
//   2. The v-menu stub below renders only the DEFAULT slot, so anything in a
//      scoped `activator` slot — the notification bell, for one — never renders
//      at all, and every "does not contain" assertion about it passes
//      vacuously. Stub v-menu locally when you need the activator.
// In all three cases the tell was the same: a negative assertion that passed on
// unchanged code. Pair negatives with a positive control that proves the thing
// under test actually rendered or ran.
vi.mock('@/composables/useToast', () => ({
  useToast: () => ({
    showToast: vi.fn()
  })
}))

// Do NOT mock useUserStore globally - tests need the real store
// Individual tests can mock the API service instead

// jsdom navigation guard (de-flake 2026-05-28)
//
// jsdom does not implement navigation, so any `window.location.href = ...`,
// `.assign()`, or `.replace()` (e.g. the OAuthAuthorize redirect) emits a
// "Not implemented: navigation to another Document" console error. Under
// parallel vitest workers that stray console output races with worker
// teardown ("Closing rpc while onUserConsoleLog was pending") and fails the
// whole run non-deterministically -- even when every test passes.
//
// Replace window.location with a plain object that preserves all read
// properties but turns navigation into no-ops, so no spec can emit the jsdom
// navigation error. Per-spec Object.defineProperty overrides still work
// (configurable: true).
{
  const realLocation = window.location
  Object.defineProperty(window, 'location', {
    configurable: true,
    writable: true,
    value: {
      href: realLocation.href,
      origin: realLocation.origin,
      protocol: realLocation.protocol,
      host: realLocation.host,
      hostname: realLocation.hostname,
      port: realLocation.port,
      pathname: realLocation.pathname,
      search: realLocation.search,
      hash: realLocation.hash,
      assign: vi.fn(),
      replace: vi.fn(),
      reload: vi.fn(),
      toString() {
        return this.href
      },
    },
  })
}

// Reset mocks before each test
beforeEach(() => {
  vi.clearAllMocks()
})

// FE-9397 (components) + FE-9403 (directives): an unresolved asset fails the
// test instead of hiding behind a green suite. `warnHandler` only records -- Vue
// runs it through `callWithErrorHandling`, so throwing there would be swallowed
// and the guard would silently not work. The throw happens here, where vitest
// reports it. Read tests/helpers/unresolvedAssetGuard.js before changing or
// removing any of this; if it fires on your spec, register the missing thing
// (stub map above for a component, `config.global.directives` for a directive)
// rather than deleting the guard.
//
// Scope is deliberate and was decided on measurement, not taste: resolution
// failures only, NOT every Vue warning. The reasoning -- including why a
// blanket policy would have been blind to the largest warning category in this
// suite -- is in the guard file's header.
//
// Deliberately NOT cleared in `beforeEach`: an asset resolved during
// `beforeAll` or at module scope warns before any test starts, and clearing up
// front would drop exactly those. Draining only here attributes them to the
// first test in the file instead of losing them.
// FE-9427: the router-injection guard is a sibling of the above, not a widening
// of it. `useRouter()` with no router installed returns `undefined` -- absence,
// not degradation -- so by the asset guard's OWN stated line it belongs on the
// fatal side. Scope is exactly two keys (see routerInjectionGuard.js); every
// other `injection not found` keeps its existing behaviour, because mounting a
// child without its provider stays a legitimate unit-testing move.
//
// One warnHandler, two recorders: the router guard gets first refusal and
// returns true when the warning was its own, so nothing is double-reported and
// nothing reaches console.warn twice.
config.global.config = {
  ...config.global.config,
  warnHandler(msg, instance, trace) {
    if (routerInjectionGuard.record(msg)) return
    unresolvedAssetGuard.warnHandler(msg, instance, trace)
  },
}

afterEach(() => {
  // Drain the router guard FIRST and unconditionally. If the asset guard throws,
  // anything the router guard recorded during this test must not survive into
  // the next one and be reported against a spec that did not cause it.
  const routerFailure = routerInjectionGuard.drainMessage()
  try {
    unresolvedAssetGuard.assertNone()
  } catch (assetFailure) {
    if (routerFailure) assetFailure.message += `\n\n${routerFailure}`
    throw assetFailure
  }
  if (routerFailure) throw new Error(routerFailure)
})
