import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '@/services/api'
import { useProjectStore } from './projects'  // Product/Project State Fix
import { useTaskStore } from './tasks'  // FE-9151: static (was a dynamic import); tasks↔products cycle is function-level only
import { immutableObjectPatch, immutableObjectDelete } from './immutableHelpers'

export const useProductStore = defineStore('products', () => {
  // Get project store for cross-store integration
  const projectStore = useProjectStore()  // Product/Project State Fix
  // State
  const products = ref([])
  const currentProductId = ref(null)
  const currentProduct = ref(null)
  const loading = ref(false)
  const error = ref(null)
  const activeProduct = ref(null)

  // FE-9121: freshest full ProductResponse per id, independent of the global
  // selection (currentProduct/currentProductId). fetchProductById/updateProduct
  // are the write path — components read an arbitrary product's freshness via
  // getProductById instead of assuming it happens to be the selected product.
  const productsById = ref({})

  // Getters
  const hasProducts = computed(() => products.value.length > 0)
  const productCount = computed(() => products.value.length)
  const getProductById = computed(() => (id) => (id ? productsById.value[id] || null : null))
  // Computed: Returns effective product ID for task operations
  // Prefers user-selected product (currentProductId) over active product
  const effectiveProductId = computed(() => {
    return currentProductId.value || activeProduct.value?.id || null
  })

  // Actions
  async function fetchProducts() {
    loading.value = true
    error.value = null
    try {
      const response = (await api.products?.list()) || { data: [] }
      products.value = response.data
    } catch (err) {
      error.value = err.message
      console.error('Failed to fetch products:', err)
    } finally {
      loading.value = false
    }
  }

  async function fetchProductById(productId) {
    if (!productId) {
      return null
    }

    loading.value = true
    error.value = null
    try {
      const response = (await api.products?.get(productId)) || { data: null }
      if (response.data) {
        productsById.value = immutableObjectPatch(productsById.value, { [productId]: response.data })
        if (productId === currentProductId.value) {
          currentProduct.value = response.data
        }
      }
      return response.data
    } catch (err) {
      error.value = err.message
      console.error('Failed to fetch product:', err)
      return null
    } finally {
      loading.value = false
    }
  }

  async function setCurrentProduct(productId) {
    if (productId === currentProductId.value && productId !== null) {
      return
    }

    await fetchProducts()

    // Handle null productId or no products available - switch to first available or clear
    if (!productId || products.value.length === 0) {
      if (products.value.length > 0) {
        // Switch to first available product
        productId = products.value[0].id
      } else {
        // No products available - clear everything
        currentProductId.value = null
        currentProduct.value = null
        localStorage.removeItem('currentProductId')
        console.warn('No products available to set as current product')
        return
      }
    }

    const product = await fetchProductById(productId)
    if (!product) {
      console.warn(`Product ${productId} not found, switching to first available`)

      if (products.value.length > 0) {
        productId = products.value[0].id
        const fallbackProduct = await fetchProductById(productId)
        if (fallbackProduct) {
          currentProductId.value = productId
          currentProduct.value = fallbackProduct
          localStorage.setItem('currentProductId', productId)
          await projectStore.fetchProjects()
          // Refresh tasks for new product
          await useTaskStore().fetchTasks({ product_id: productId })
          window.dispatchEvent(
            new CustomEvent('product-changed', {
              detail: { productId, product: fallbackProduct },
            }),
          )
        }
        return
      } else {
        currentProductId.value = null
        currentProduct.value = null
        localStorage.removeItem('currentProductId')
        return
      }
    }

    currentProductId.value = productId
    currentProduct.value = product

    localStorage.setItem('currentProductId', productId)

    // Product/Project State Fix: Refresh dependent stores when product changes
    await projectStore.fetchProjects()
    // Refresh tasks for new product
    await useTaskStore().fetchTasks({ product_id: productId })

    window.dispatchEvent(
      new CustomEvent('product-changed', {
        detail: { productId, product },
      }),
    )
  }

  async function createProduct(productData) {
    loading.value = true
    error.value = null
    try {
      const response = (await api.products?.create(productData)) || { data: null }
      if (response.data) {
        products.value.push(response.data)
      }
      return response.data
    } catch (err) {
      error.value = err.message
      console.error('Failed to create product:', err)
      throw err
    } finally {
      loading.value = false
    }
  }

  async function updateProduct(productId, updates) {
    loading.value = true
    error.value = null
    try {
      const response = (await api.products?.update(productId, updates)) || { data: null }
      if (response.data) {
        const index = products.value.findIndex((p) => p.id === productId)
        if (index !== -1) {
          products.value[index] = response.data
        }
        if (productId === currentProductId.value) {
          currentProduct.value = response.data
        }
        productsById.value = immutableObjectPatch(productsById.value, { [productId]: response.data })
      }
      return response.data
    } catch (err) {
      error.value = err.message
      console.error('Failed to update product:', err)
      throw err
    } finally {
      loading.value = false
    }
  }

  async function deleteProduct(productId) {
    loading.value = true
    error.value = false
    try {
      await api.products?.delete(productId)
      products.value = products.value.filter((p) => p.id !== productId)
      productsById.value = immutableObjectDelete(productsById.value, productId)

      if (productId === currentProductId.value) {
        await setCurrentProduct(null)
      }
    } catch (err) {
      error.value = err.message
      console.error('Failed to delete product:', err)
      throw err
    } finally {
      loading.value = false
    }
  }

  async function fetchActiveProduct() {
    try {
      // Use dedicated active-product endpoint for accurate status
      const response = await api.products.getActive()
      const data = response?.data || { has_active_product: false, product: null }
      if (data.has_active_product && data.product) {
        activeProduct.value = data.product
      } else {
        activeProduct.value = null
      }
      return true
    } catch (err) {
      console.error('Failed to fetch active product:', err)
      activeProduct.value = null
      // FE-9412: report the read failure so callers can tell "the server says
      // there is no active product" apart from "the server did not answer".
      // Existing callers ignore the return and keep their current behaviour.
      return false
    }
  }

  async function initializeFromStorage() {
    try {
      // Auth guard removed — caller (DefaultLayout) already verified user is authenticated.
      // Previous guard checked localStorage('auth_token') which is always null (httpOnly cookies).

      await fetchProducts()

      const storedProductId = localStorage.getItem('currentProductId')
      if (storedProductId && products.value.length > 0) {
        const product = products.value.find((p) => p.id === parseInt(storedProductId))
        if (product) {
          await setCurrentProduct(parseInt(storedProductId))
        } else {
          localStorage.removeItem('currentProductId')
          await setCurrentProduct(products.value[0].id)
        }
      } else if (products.value.length > 0) {
        await setCurrentProduct(products.value[0].id)
      }

      await fetchActiveProduct()
    } catch (error) {
      console.error('[PRODUCTS] Failed to initialize from storage:', error)
    }
  }

  function clearProductData() {
    products.value = []
    currentProductId.value = null
    currentProduct.value = null
    activeProduct.value = null
    productsById.value = {}
    localStorage.removeItem('currentProductId')
  }

  // ============================================
  // WEBSOCKET EVENT HANDLERS (Handover 0139b)
  // ============================================

  /**
   * Handle product:memory:updated event
   * Updates product memory when backend emits changes
   */
  function handleProductMemoryUpdated(payload) {
    if (!payload?.product_id) {
      console.warn('[PRODUCTS] product:memory:updated missing product_id', payload)
      return
    }

    const product = products.value.find((p) => p.id === payload.product_id)
    const nextMemory = payload.product_memory || payload.data?.product_memory

    if (product && nextMemory) {
      // Update product memory
      product.product_memory = nextMemory

      // Also update currentProduct if it matches
      if (currentProduct.value?.id === payload.product_id) {
        currentProduct.value.product_memory = nextMemory
      }

    }
  }

  /**
   * FE-9412: reconcile this session against the server's active product.
   *
   * Re-reads the active product and, when it no longer matches what this
   * session is scoped by, re-scopes through setCurrentProduct() — the same
   * call the local activation path makes (useProductActivation), so a session
   * that learns about an activation second-hand lands in the same state as the
   * one that performed it: header, project list, tasks and roadmap together.
   *
   * The live WS event and the focus/reconnect backstop both come through here,
   * so the two paths cannot drift apart.
   */
  async function revalidateActiveProduct() {
    // This runs on every tab focus, so a flaky network must not be able to
    // blank the header or move the session: on a failed read, put back what
    // the session already had and change nothing.
    const previousActive = activeProduct.value
    const read = await fetchActiveProduct()
    if (!read) {
      activeProduct.value = previousActive
      return
    }

    const serverActiveId = activeProduct.value?.id
    // No active product on the server (e.g. a deactivation) leaves this
    // session's selection alone — there is nothing to re-scope to.
    if (!serverActiveId || serverActiveId === currentProductId.value) {
      return
    }

    await setCurrentProduct(serverActiveId)
  }

  /**
   * Handle product status change events by reconciling the active product.
   */
  async function handleProductStatusChanged() {
    try {
      await revalidateActiveProduct()
    } catch (e) {
      console.warn('[PRODUCTS] Failed to refresh active product on WS event:', e)
    }
  }

  return {
    // State
    products,
    currentProductId,
    currentProduct,
    loading,
    error,
    activeProduct,
    productsById,

    // Getters
    hasProducts,
    productCount,
    effectiveProductId,
    getProductById,

    // Actions
    fetchProducts,
    setCurrentProduct,
    fetchProductById,
    createProduct,
    updateProduct,
    deleteProduct,
    fetchActiveProduct,
    revalidateActiveProduct,
    initializeFromStorage,
    clearProductData,

    // WebSocket router handlers (0379a)
    handleProductMemoryUpdated,
    handleProductStatusChanged,
  }
})
