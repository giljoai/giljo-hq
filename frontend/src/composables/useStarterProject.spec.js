import { beforeEach, describe, expect, it, vi } from 'vitest'

const h = vi.hoisted(() => ({
  productId: 'prod-1',
  create: vi.fn(),
  push: vi.fn(),
  toast: vi.fn(),
}))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: h.push }) }))
vi.mock('@/stores/products', () => ({
  useProductStore: () => ({ get effectiveProductId() { return h.productId } }),
}))
vi.mock('@/stores/projects', () => ({ useProjectStore: () => ({ createProject: (...a) => h.create(...a) }) }))
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: (...a) => h.toast(...a) }) }))

import { useStarterProject } from '@/composables/useStarterProject'
import { PROJECT_TEMPLATES } from '@/composables/projectTemplates'

const tmpl = PROJECT_TEMPLATES[1]

describe('useStarterProject', () => {
  beforeEach(() => {
    h.productId = 'prod-1'
    Object.values(h).forEach((v) => v?.mockReset?.())
    h.create.mockResolvedValue({})
  })

  it('creates the template project under the viewed product, then goes to Projects', async () => {
    const { createFromTemplate, busyTemplateId } = useStarterProject()
    const p = createFromTemplate(tmpl)
    expect(busyTemplateId.value).toBe(tmpl.id)
    await p
    expect(h.create).toHaveBeenCalledWith({
      name: tmpl.projectName,
      description: tmpl.projectDescription,
      product_id: 'prod-1',
    })
    expect(h.push).toHaveBeenCalledWith('/Projects')
    expect(busyTemplateId.value).toBe(null)
  })

  it('with no product open it says so and creates nothing', async () => {
    h.productId = null
    const { createFromTemplate } = useStarterProject()
    await createFromTemplate(tmpl)
    expect(h.create).not.toHaveBeenCalled()
    expect(h.toast).toHaveBeenCalledWith({
      message: 'No product is open. Add a product before creating a project.',
      color: 'error',
    })
  })

  it('a second press while one is running is ignored', async () => {
    const { createFromTemplate } = useStarterProject()
    const first = createFromTemplate(tmpl)
    await createFromTemplate(PROJECT_TEMPLATES[0])
    await first
    expect(h.create).toHaveBeenCalledTimes(1)
  })

  it('a failed create shows the error and frees the button', async () => {
    h.create.mockRejectedValue(new Error('nope'))
    const { createFromTemplate, busyTemplateId } = useStarterProject()
    await createFromTemplate(tmpl)
    expect(h.toast).toHaveBeenCalledWith({ message: 'nope', color: 'error' })
    expect(busyTemplateId.value).toBe(null)
    expect(h.push).not.toHaveBeenCalled()
  })
})
