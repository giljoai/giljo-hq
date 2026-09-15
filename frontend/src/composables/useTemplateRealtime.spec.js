
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { ref, defineComponent } from 'vue'
import { mount } from '@vue/test-utils'
import { useTemplateRealtime } from '@/composables/useTemplateRealtime'


function makeTemplates() {
  return [
    { id: 1, name: 'Analyzer', is_active: true },
    { id: 2, name: 'Reviewer', is_active: false },
  ]
}

function mountHost() {
  const templates = ref(makeTemplates())
  const reloadActiveCount = vi.fn()

  const Host = defineComponent({
    setup() {
      useTemplateRealtime(templates, reloadActiveCount)
      return () => null
    },
  })

  const wrapper = mount(Host)

  return { wrapper, templates, reloadActiveCount }
}

const dispatch = (name, detail) => window.dispatchEvent(new CustomEvent(name, { detail }))


describe('useTemplateRealtime — template:updated', () => {
  let ctx

  beforeEach(() => {
    ctx = mountHost()
  })

  it('mirrors is_active onto the addressed row', () => {
    dispatch('template:updated', { template_id: 2, is_active: true })

    const row = ctx.templates.value.find((t) => t.id === 2)
    expect(row.is_active).toBe(true)
  })

  it('applies an explicit false — false is not absent', () => {
    dispatch('template:updated', { template_id: 1, is_active: false })

    expect(ctx.templates.value.find((t) => t.id === 1).is_active).toBe(false)
  })

  it('ignores an event with no template_id', () => {
    dispatch('template:updated', { is_active: false })

    expect(ctx.templates.value.map((t) => t.is_active)).toEqual([true, false])
  })

  it('ignores an event addressing a template that is not on screen', () => {
    dispatch('template:updated', { template_id: 999, is_active: false })

    expect(ctx.templates.value.map((t) => t.is_active)).toEqual([true, false])
  })

  it('refreshes the active count when updated_fields includes is_active', () => {
    dispatch('template:updated', {
      template_id: 1,
      is_active: false,
      updated_fields: ['is_active'],
    })

    expect(ctx.reloadActiveCount).toHaveBeenCalledTimes(1)
  })

  it('does NOT refresh the active count for an unrelated field change', () => {
    dispatch('template:updated', {
      template_id: 1,
      is_active: false,
      updated_fields: ['description'],
    })

    expect(ctx.reloadActiveCount).not.toHaveBeenCalled()
  })
})


describe('useTemplateRealtime — teardown', () => {
  it('stops responding to template:updated after unmount', () => {
    const ctx = mountHost()

    ctx.wrapper.unmount()

    dispatch('template:updated', {
      template_id: 1,
      is_active: false,
      updated_fields: ['is_active'],
    })

    expect(ctx.templates.value.map((t) => t.is_active)).toEqual([true, false])
    expect(ctx.reloadActiveCount).not.toHaveBeenCalled()
  })
})
