import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'

import TemplatesTable from './TemplatesTable.vue'
import { TEMPLATE_TABLE_HEADERS } from './templateTableConfig.js'

const dataTableStub = {
  props: ['headers', 'items', 'loading', 'search', 'itemsPerPage'],
  template: `
    <div class="v-data-table">
      <div v-for="item in (items || [])" :key="item.id" class="v-data-table-row">
        <slot name="item.name" :item="item" />
      </div>
    </div>
  `,
}

const row = (id, name) => ({ id, name, role: 'analyzer', is_active: true, _system: false })

function mountTable(props = {}) {
  return mount(TemplatesTable, {
    props: {
      templates: [row('t-1', 'analyzer'), row('t-2', 'reviewer')],
      headers: TEMPLATE_TABLE_HEADERS,
      ...props,
    },
    global: { stubs: { 'v-data-table': dataTableStub } },
  })
}

describe('TemplatesTable — proposal badge (BE-9755)', () => {
  it('shows a badge only on rows with a waiting proposal', () => {
    const w = mountTable({ proposalTemplateIds: ['t-2'] })
    expect(w.find('[data-testid="proposal-badge-t-1"]').exists()).toBe(false)
    expect(w.get('[data-testid="proposal-badge-t-2"]').text()).toContain('Change proposed')
  })

  it('shows no badge when nothing is waiting (prop omitted)', () => {
    const w = mountTable()
    expect(w.findAll('[data-testid^="proposal-badge-"]')).toHaveLength(0)
  })

  it('clicking the badge emits open-proposal with the row', async () => {
    const w = mountTable({ proposalTemplateIds: ['t-1'] })
    await w.get('[data-testid="proposal-badge-t-1"]').trigger('click')
    expect(w.emitted('open-proposal')[0][0]).toMatchObject({ id: 't-1' })
  })
})
