/**
 * AgentMissionEditModal — BE-9416: never seed the editor from a truncated mission.
 *
 * agent:created / agent:mission_updated now bound the mission they carry so it
 * clears the cross-worker broker's pg_notify byte cap, flagging it with
 * `mission_truncated`; agentJobsStore then fetches the full text and patches the
 * row. This editor is the dangerous reader: it SAVES what it is seeded with, so an
 * excerpt seeded here and saved would overwrite the real mission with a fragment
 * of itself — silent data loss, caused by the fix for a data loss.
 *
 * Two guards pinned here:
 *  1. a truncated mission is never seeded, and Save stays unavailable until the
 *     full text lands (a guard that merely RE-SEEDS correctly still leaves a fast
 *     operator able to save the excerpt in the window before the top-up returns)
 *  2. the top-up must never clobber edits already in progress — it patches the
 *     store row, which re-fires the seed watch
 *
 * Edition Scope: Both
 */

import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { createVuetify } from 'vuetify'
import { nextTick } from 'vue'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'
import AgentMissionEditModal from '@/components/projects/AgentMissionEditModal.vue'

const EXCERPT = 'the first five kilobytes of a very long orchestrator mission'
const FULL_MISSION = `${EXCERPT} ... and the forty-five kilobytes the broker could not carry`

describe('AgentMissionEditModal — BE-9416 truncated-mission guards', () => {
  let wrapper
  let pinia
  let vuetify
  let mockApiClient

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    vuetify = createVuetify({ components, directives })
    mockApiClient = {
      agentJobs: {
        updateMission: vi.fn().mockResolvedValue({ data: { success: true, job_id: 'job-1', mission: 'x' } }),
      },
    }
  })

  afterEach(() => {
    if (wrapper) wrapper.unmount()
    vi.restoreAllMocks()
  })

  const truncatedAgent = {
    id: 'job-1',
    job_id: 'job-1',
    agent_display_name: 'orchestrator',
    mission: EXCERPT,
    mission_truncated: true,
    mission_length: FULL_MISSION.length,
  }

  const wholeAgent = {
    ...truncatedAgent,
    mission: FULL_MISSION,
    mission_truncated: false,
    mission_length: FULL_MISSION.length,
  }

  const createWrapper = (agent) =>
    mount(AgentMissionEditModal, {
      props: { modelValue: true, agent },
      global: { plugins: [pinia, vuetify], mocks: { $api: mockApiClient } },
      attachTo: document.body,
    })

  it('does not seed the editor from a truncated mission', async () => {
    wrapper = createWrapper(truncatedAgent)
    await nextTick()

    expect(wrapper.vm.missionText).toBe('')
    expect(wrapper.vm.originalMission).toBe('')
    // The excerpt must not be reachable as editable text at all — this is the
    // assertion that fails if someone "helpfully" seeds the partial value.
    expect(wrapper.vm.missionText).not.toContain(EXCERPT)
  })

  it('keeps Save unavailable while the full mission is still in flight', async () => {
    wrapper = createWrapper(truncatedAgent)
    await nextTick()

    // hasChanges gates the Save button; with nothing seeded and nothing typed it
    // is false, so an excerpt cannot be saved over the real mission.
    expect(wrapper.vm.hasChanges).toBe(false)
    expect(wrapper.vm.missionPending).toBe(true)
  })

  it('seeds normally once the top-up lands', async () => {
    wrapper = createWrapper(truncatedAgent)
    await nextTick()
    expect(wrapper.vm.missionText).toBe('')

    // The store patches the row; the modal's prop is the same reactive entity.
    await wrapper.setProps({ agent: wholeAgent })
    await nextTick()

    expect(wrapper.vm.missionText).toBe(FULL_MISSION)
    expect(wrapper.vm.originalMission).toBe(FULL_MISSION)
    expect(wrapper.vm.missionPending).toBe(false)
    expect(wrapper.vm.hasChanges).toBe(false)
  })

  it('never clobbers an edit already in progress when the top-up arrives', async () => {
    // The hazard this fix introduces: the top-up patches the store row, re-firing
    // the seed watch. Without the hasChanges guard the operator's typing vanishes.
    wrapper = createWrapper(wholeAgent)
    await nextTick()

    wrapper.vm.missionText = 'the operator is halfway through rewriting this'
    await nextTick()
    expect(wrapper.vm.hasChanges).toBe(true)

    await wrapper.setProps({ agent: { ...wholeAgent, mission: `${FULL_MISSION} (changed elsewhere)` } })
    await nextTick()

    expect(wrapper.vm.missionText).toBe('the operator is halfway through rewriting this')
  })

  it('is unaffected for an ordinary mission that travelled whole', async () => {
    wrapper = createWrapper(wholeAgent)
    await nextTick()

    expect(wrapper.vm.missionText).toBe(FULL_MISSION)
    expect(wrapper.vm.missionPending).toBe(false)
  })
})
