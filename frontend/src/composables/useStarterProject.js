import { ref } from 'vue'
import { useRouter } from 'vue-router'

import { useToast } from '@/composables/useToast'
import { useProductStore } from '@/stores/products'
import { useProjectStore } from '@/stores/projects'

export function useStarterProject() {
  const router = useRouter()
  const productStore = useProductStore()
  const projectStore = useProjectStore()
  const { showToast } = useToast()
  const busyTemplateId = ref(null)

  async function createFromTemplate(tmpl) {
    if (busyTemplateId.value) return
    const productId = productStore.effectiveProductId
    if (!productId) {
      showToast({
        message: 'No product is open. Add a product before creating a project.',
        color: 'error',
      })
      return
    }
    busyTemplateId.value = tmpl.id
    try {
      await projectStore.createProject({
        name: tmpl.projectName,
        description: tmpl.projectDescription,
        product_id: productId,
      })
      busyTemplateId.value = null
      router.push('/Projects')
    } catch (err) {
      busyTemplateId.value = null
      showToast({
        message: err?.message || 'Failed to create project from template',
        color: 'error',
      })
    }
  }

  return { busyTemplateId, createFromTemplate }
}
