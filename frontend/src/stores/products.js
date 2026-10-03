import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '@/services/api'
import { useProjectStore } from './projects'
import { useTaskStore } from './tasks'
import { useCommHubStore } from './commHubStore'
import { immutableObjectPatch, immutableObjectDelete } from './immutableHelpers'

export const useProductStore = defineStore('products', () => {
  const projectStore = useProjectStore()
  const products = ref([])
  const currentProductId = ref(null)
  const currentProduct = ref(null)
  const loading = ref(false)
  const error = ref(null)
  const activeProduct = ref(null)

  const productsById = ref({})

  const openProductIds = computed(() => products.value.filter((p) => p.is_active).map((p) => p.id))

  const hasProducts = computed(() => products.value.length > 0)
  const productCount = computed(() => products.value.length)
  const getProductById = computed(() => (id) => (id ? productsById.value[id] || null : null))
  const openProductTabs = computed(() =>
    openProductIds.value
      .map((id) => products.value.find((p) => p.id === id) || productsById.value[id] || null)
      .filter(Boolean),
  )
  const effectiveProductId = computed(() => {
    return currentProductId.value || activeProduct.value?.id || null
  })

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

  function _clearCurrentProduct() {
    currentProductId.value = null
    currentProduct.value = null
    localStorage.removeItem('currentProductId')
  }

  async function _applyCurrentProduct(productId, product) {
    currentProductId.value = productId
    currentProduct.value = product
    localStorage.setItem('currentProductId', productId)
    await projectStore.fetchProjects()
    await useTaskStore().fetchTasks({ product_id: productId })
    await useCommHubStore().loadThreads({ product_id: productId })
    window.dispatchEvent(new CustomEvent('product-changed', { detail: { productId, product } }))
  }

  async function setCurrentProduct(productId) {
    if (productId === currentProductId.value && productId !== null) {
      return
    }

    await fetchProducts()

    if (products.value.length === 0) {
      _clearCurrentProduct()
      console.warn('No products available to set as current product')
      return
    }
    if (!productId) productId = products.value[0].id

    const product = await fetchProductById(productId)
    if (product) {
      await _applyCurrentProduct(productId, product)
      return
    }

    console.warn(`Product ${productId} not found, switching to first available`)
    const fallbackId = products.value[0].id
    const fallbackProduct = await fetchProductById(fallbackId)
    if (fallbackProduct) await _applyCurrentProduct(fallbackId, fallbackProduct)
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

      if (activeProduct.value?.id === productId) {
        await fetchActiveProduct()
      }
    } catch (err) {
      error.value = err.message
      console.error('Failed to delete product:', err)
      throw err
    } finally {
      loading.value = false
    }
  }

  async function setDefaultProduct(productId) {
    loading.value = true
    error.value = null
    try {
      const response = (await api.products?.setDefault(productId)) || { data: null }
      const updated = response.data
      if (updated) {
        products.value = products.value.map((p) => {
          if (p.id === updated.id) return updated
          if (p.is_default) return { ...p, is_default: false }
          return p
        })
        productsById.value = immutableObjectPatch(productsById.value, { [updated.id]: updated })
        if (updated.id === currentProductId.value) {
          currentProduct.value = updated
        }
      }
      await fetchActiveProduct()
      return updated
    } catch (err) {
      error.value = err.message
      console.error('Failed to set default product:', err)
      throw err
    } finally {
      loading.value = false
    }
  }

  async function fetchActiveProduct() {
    try {
      const response = await api.products.getDefault()
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
      return false
    }
  }

  async function initializeFromStorage() {
    try {

      await fetchProducts()

      const storedProductId = localStorage.getItem('currentProductId')
      if (storedProductId && products.value.length > 0) {
        const product = products.value.find((p) => p.id === storedProductId)
        if (product) {
          await setCurrentProduct(storedProductId)
        } else {
          localStorage.removeItem('currentProductId')
          await setCurrentProduct(products.value[0].id)
        }
      } else if (products.value.length > 0) {
        await setCurrentProduct(products.value[0].id)
      }

      await migrateLocalTabsToServer()

      await fetchActiveProduct()
    } catch (error) {
      console.error('[PRODUCTS] Failed to initialize from storage:', error)
    }
  }

  async function migrateLocalTabsToServer() {
    let storedOpenIds = null
    try {
      const raw = localStorage.getItem('openProductTabIds')
      storedOpenIds = raw ? JSON.parse(raw) : null
    } catch {
      storedOpenIds = null
    }
    if (!storedOpenIds) {
      return
    }

    const idsToShow = new Set(storedOpenIds.filter((id) => products.value.some((p) => p.id === id)))
    if (currentProductId.value) {
      idsToShow.add(currentProductId.value)
    }

    const alreadyShown = new Set(openProductIds.value)
    const toActivate = [...idsToShow].filter((id) => !alreadyShown.has(id))
    if (toActivate.length > 0) {
      await Promise.all(toActivate.map((id) => api.products?.activate(id)))
      await fetchProducts()
    }

    try {
      localStorage.removeItem('openProductTabIds')
    } catch {
      // localStorage unavailable -- nothing to clean up.
    }
  }

  async function openTab(productId) {
    if (!productId) {
      return
    }
    if (!openProductIds.value.includes(productId)) {
      await api.products?.activate(productId)
      await fetchProducts()
    }
    await switchTab(productId)
  }

  async function switchTab(productId) {
    await setCurrentProduct(productId)
  }

  async function closeTab(productId) {
    const currentIds = openProductIds.value
    if (!currentIds.includes(productId) || currentIds.length <= 1) {
      return
    }

    const closingIndex = currentIds.indexOf(productId)
    const nextIds = currentIds.filter((id) => id !== productId)

    await api.products?.deactivate(productId)
    await fetchProducts()

    if (productId === currentProductId.value) {
      const nextViewedId = nextIds[Math.min(closingIndex, nextIds.length - 1)]
      await switchTab(nextViewedId)
    }
  }

  function clearProductData() {
    products.value = []
    currentProductId.value = null
    currentProduct.value = null
    activeProduct.value = null
    productsById.value = {}
    localStorage.removeItem('currentProductId')
    localStorage.removeItem('openProductTabIds')
  }


  async function revalidateActiveProduct() {
    const previousActive = activeProduct.value
    const read = await fetchActiveProduct()
    if (!read) {
      activeProduct.value = previousActive
    }
  }

  async function handleProductStatusChanged() {
    try {
      await revalidateActiveProduct()
    } catch (e) {
      console.warn('[PRODUCTS] Failed to refresh active product on WS event:', e)
    }
  }

  return {
    products,
    currentProductId,
    currentProduct,
    loading,
    error,
    activeProduct,
    productsById,

    hasProducts,
    productCount,
    effectiveProductId,
    getProductById,
    openProductIds,
    openProductTabs,

    fetchProducts,
    setCurrentProduct,
    fetchProductById,
    createProduct,
    updateProduct,
    deleteProduct,
    setDefaultProduct,
    fetchActiveProduct,
    revalidateActiveProduct,
    initializeFromStorage,
    clearProductData,
    openTab,
    switchTab,
    closeTab,

    handleProductStatusChanged,
  }
})
