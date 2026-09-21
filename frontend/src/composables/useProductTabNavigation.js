import { useRoute, useRouter } from 'vue-router'
import { useProductStore } from '@/stores/products'
import { useProjectStore } from '@/stores/projects'
import { useProductActivityStore } from '@/stores/productActivityStore'

const PROJECT_SCOPED_ROUTES = new Set(['ProjectLaunch'])

export function useProductTabNavigation() {
  const route = useRoute()
  const router = useRouter()
  const productStore = useProductStore()
  const projectStore = useProjectStore()
  const productActivityStore = useProductActivityStore()

  function routeLeavesProduct(nextProductId) {
    if (!PROJECT_SCOPED_ROUTES.has(route.name)) return false
    const owner = projectStore.projectById(route.params.projectId)?.product_id
    return !!owner && owner !== nextProductId
  }

  async function selectTab(productId) {
    const leaving = routeLeavesProduct(productId)

    await productStore.switchTab(productId)
    productActivityStore.clearActivity(productId)

    if (leaving) {
      await router.push({ name: 'Projects' })
    }
  }

  return { selectTab }
}
