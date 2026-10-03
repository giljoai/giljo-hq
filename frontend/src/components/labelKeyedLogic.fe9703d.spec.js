import { describe, it, expect, vi } from 'vitest'
import { ref, computed } from 'vue'
import { mount } from '@vue/test-utils'
import { createVuetify } from 'vuetify'
import { createPinia } from 'pinia'

vi.mock('@/composables/useProjectStageControls', () => ({
  useProjectStageControls: () => ({
    detectedHarness: ref('claude-code'),
    canImplement: computed(() => false),
    readyToLaunch: computed(() => false),
    launched: computed(() => false),
    executionPlatform: ref('claude-code'),
    executionMode: ref('subagent'),
    executionModeSelected: computed(() => true),
    isExecutionModeLocked: computed(() => true),
    modeRefused: ref(false),
    isProjectStaging: computed(() => false),
    isProjectStaged: computed(() => false),
    canRestage: computed(() => true),
    handleExecutionModeChange: vi.fn(),
    loadingStageProject: ref(false),
    handleStageOrRestage: vi.fn(),
    handleLaunchJobs: vi.fn(),
    stageButtonText: computed(() => 'Stage again'),
    stageButtonDisabled: computed(() => false),
    stageButtonTitle: computed(() => ''),
  }),
}))

import ThreadCard from '@/components/hub/ThreadCard.vue'
import JobsBoardCardFooter from '@/components/projects/JobsBoardCardFooter.vue'
import { JOBS_SECTION_LABELS } from '@/utils/jobsSectionLabel'

const vuetify = createVuetify()

describe('ThreadCard: the name is a name', () => {
  it('a thread named by its user shows that name even when it starts with "chain run"', () => {
    const w = mount(ThreadCard, {
      props: {
        thread: {
          thread_id: 't1',
          chat_id: 'CHT-0001',
          subject: 'Chain run retrospective',
          status: 'open',
          project_id: null,
          sequence_run_id: 'run-1',
          participants: [],
          last_message: null,
          unread: false,
        },
      },
      global: { plugins: [vuetify] },
    })
    expect(w.text()).toContain('Chain run retrospective')
    expect(w.text()).not.toContain('Untitled thread')
  })
})

describe('JobsBoardCardFooter: the Stage button look follows the state', () => {
  it('a re-stageable project gets the secondary look whatever the button says', () => {
    const w = mount(JobsBoardCardFooter, {
      props: {
        project: { id: 'p1', taxonomy_alias: 'FE-0001', name: 'P', status: 'active', staging_status: 'staging_complete' },
        sectionLabel: JOBS_SECTION_LABELS.ACTIVATED,
      },
      global: {
        plugins: [createPinia()],
        stubs: { 'v-tooltip': { template: '<div><slot name="activator" :props="{}" /><slot /></div>' } },
      },
    })
    const btn = w.find('[data-testid="jbf-stage"]')
    expect(btn.text()).toBe('Stage again')
    expect(btn.classes()).toContain('jb-btn-secondary')
  })
})
