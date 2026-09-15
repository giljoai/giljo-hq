import { useRouter } from 'vue-router'
import api from '@/services/api'
import { useProductStore } from '@/stores/products'
import { useToast } from '@/composables/useToast'

export function useProductActivation(loadProducts) {
  const productStore = useProductStore()
  const { showToast } = useToast()
  const router = useRouter()

  async function toggleProductActivation(product) {
    try {
      if (product.is_active) {
        await api.products.deactivate(product.id)

        showToast({
          message: `${product.name} hidden`,
          type: 'info',
          timeout: 3000,
        })

        await loadProducts()
      } else {
        await productStore.openTab(product.id)

        showToast({
          message: `${product.name} shown`,
          type: 'success',
          timeout: 3000,
        })

        await loadProducts()
        router.push('/home')
      }
    } catch (error) {
      console.error('Failed to toggle product visibility:', error)
      showToast({
        message: 'Failed to change product visibility. Try again or refresh the page.',
        type: 'error',
        timeout: 5000,
      })
    }
  }

  return {
    toggleProductActivation,
  }
}
