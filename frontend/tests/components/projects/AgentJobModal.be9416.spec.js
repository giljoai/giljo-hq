/**
 * AgentJobModal — BE-9416: a truncated mission must not freeze into the snapshot.
 *
 * The modal deliberately snapshots the agent row on open (`toRaw`) to disconnect
 * the open dialog from live WebSocket churn. That is load-bearing and stays.
 *
 * But agent:created / agent:mission_updated now carry a BOUNDED mission (it has to
 * clear the cross-worker broker's pg_notify byte cap), so a modal opened in the
 * window before agentJobsStore's top-up lands would freeze an EXCERPT and render it
 * as the whole mission with nothing to say otherwise.
 *
 * Pinned here: the snapshot adopts the full text on the truncated -> whole
 * transition, and ONLY on that transition — ordinary status churn must still be
 * unable to reach the snapshot, or the disconnect it exists for is gone.
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
import AgentJobModal from '@/components/projects/AgentJobModal.vue'

const EXCERPT = 'the first five kilobytes of a very long orchestrator mission'
const FULL_MISSION = `${EXCERPT} ... and the forty-five kilobytes the broker could not carry`

describe('AgentJobModal — BE-9416 snapshot adopts a topped-up mission', () => {
  let wrapper
  let pinia
  let vuetify

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    vuetify = createVuetify({ components, directives })
  })

  afterEach(() => {
    if (wrapper) wrapper.unmount()
    vi.restoreAllMocks()
  })

  const truncatedAgent = {
    agent_id: 'agent-1',
    job_id: 'job-1',
    agent_display_name: 'orchestrator',
    agent_name: 'orchestrator',
    status: 'waiting',
    mission: EXCERPT,
    mission_truncated: true,
    mission_length: FULL_MISSION.length,
  }

  // The snapshot is taken by a watcher on `show` WITHOUT immediate:true, so
  // mounting straight into show:true never takes one and displayAgent quietly
  // falls back to the live prop. Every test here must drive the real false->true
  // transition or it verifies nothing about the snapshot at all.
  const openWith = async (agent) => {
    const w = mount(AgentJobModal, {
      props: { show: false, agent },
      global: { plugins: [pinia, vuetify] },
      attachTo: document.body,
    })
    await w.setProps({ show: true })
    await nextTick()
    return w
  }

  it('adopts the full mission when the top-up lands', async () => {
    wrapper = await openWith(truncatedAgent)
    expect(wrapper.vm.agentSnapshot, 'the snapshot must exist or this test proves nothing').toBeTruthy()
    expect(wrapper.vm.displayAgent.mission).toBe(EXCERPT)

    await wrapper.setProps({
      agent: { ...truncatedAgent, mission: FULL_MISSION, mission_truncated: false },
    })
    await nextTick()

    expect(wrapper.vm.displayAgent.mission).toBe(FULL_MISSION)
    expect(wrapper.vm.displayAgent.mission_truncated).toBe(false)
  })

  it('still ignores ordinary live churn — the snapshot disconnect is intact', async () => {
    // The whole point of the snapshot. If this starts failing, the narrow watch
    // has been widened into a general live binding and BE-0457's disconnect is gone.
    wrapper = await openWith({ ...truncatedAgent, mission: FULL_MISSION, mission_truncated: false })

    await wrapper.setProps({
      agent: { ...truncatedAgent, mission: FULL_MISSION, mission_truncated: false, status: 'working' },
    })
    await nextTick()

    expect(wrapper.vm.displayAgent.status).toBe('waiting')
  })

  it('does not resurrect a snapshot after the modal is closed', async () => {
    wrapper = await openWith(truncatedAgent)

    await wrapper.setProps({ show: false })
    await nextTick()

    await wrapper.setProps({
      agent: { ...truncatedAgent, mission: FULL_MISSION, mission_truncated: false },
    })
    await nextTick()

    // agentSnapshot is null while closed; displayAgent falls back to the live prop.
    // The guard must not have rebuilt a snapshot out of nothing.
    expect(wrapper.vm.displayAgent.mission).toBe(FULL_MISSION)
  })
})
