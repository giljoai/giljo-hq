import { useRouter } from 'vue-router'
import api from '@/services/api'
import { useProductStore } from '@/stores/products'
import { useToast } from '@/composables/useToast'

/**
 * FE-9524/D1: the product-card button's Show/Hide toggle. Every product may
 * be shown at once, so there is nothing left to warn about when showing one
 * -- the old "you're about to switch away from your currently active
 * product" ceremony (showActivationWarning/pendingActivation/
 * currentActiveProduct + ActivationWarningDialog) never armed here and was
 * proven zero-caller (FE-9529): the dialog and those three inert refs are
 * deleted.
 */
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
        // openTab both shows the product (server write) and switches the
        // viewed tab to it -- still the entry point to per-product
        // onboarding, just tab-aware (FE-9502c).
        await productStore.openTab(product.id)

        showToast({
          message: `${product.name} shown`,
          type: 'success',
          timeout: 3000,
        })

        await loadProducts()
        // Showing a product is the universal entry point to per-product
        // onboarding: route to /home so the user sees New Project + bootstrap
        // cards (when applicable -- gated by Product.first_project_created_at).
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
