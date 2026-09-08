import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '@/services/api'
import { useProjectStore } from './projects'  // Product/Project State Fix
import { useTaskStore } from './tasks'  // FE-9151: static (was a dynamic import); tasks↔products cycle is function-level only
import { useCommHubStore } from './commHubStore'  // FE-9528: products↔commHub cycle is function-level only, same as tasks above
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
  // FE-9529: `activeProduct` and `currentProductId` answer two DELIBERATELY
  // DIFFERENT questions and neither is vestigial -- conflating them is the
  // exact defect BE-9525a/FE-9524 fixed. Kept as the field name (not renamed
  // to `defaultProduct`) because ~15 consumer files + specs already thread
  // "activeProduct" through as an established local-naming convention for
  // "the product a component is scoped to" (ProjectsView/RoadmapView's own
  // `activeProduct` computed, useProjectFilters' param, etc.) that is
  // UNRELATED to this ref; a field rename would touch all of them for a
  // naming-clarity win with no behavior change, out of proportion to this
  // project. The two concepts:
  //   - `activeProduct` = the resolved DEFAULT product (GET /refresh-active,
  //     ProductService.get_default_product): where an UNSCOPED READ goes
  //     when nothing else says. Tenant-wide, single-valued, a display value
  //     only -- never authoritative UI state, never re-scopes the session.
  //   - `currentProductId` = the VIEWED TAB: UI-local, per-viewer, never
  //     touched by a fetch of the other.
  const activeProduct = ref(null)

  // FE-9121: freshest full ProductResponse per id, independent of the global
  // selection (currentProduct/currentProductId). fetchProductById/updateProduct
  // are the write path — components read an arbitrary product's freshness via
  // getProductById instead of assuming it happens to be the selected product.
  const productsById = ref({})

  // FE-9524/D1: which products are open as tabs is SERVER state --
  // products.is_active, REUSED from "the one active product" to "shown as a
  // tab in my strip" (idx_product_single_active_per_tenant dropped, ce_0099).
  // FE-9502c originally shipped this as a UI-local `openProductIds` ref backed
  // by localStorage; that ref is now DERIVED from `products` so every tab
  // action (openTab/closeTab) is a server write and the same tabs show up on
  // any machine. currentProductId (the VIEWED tab) stays UI-local/localStorage
  // -- unaffected, per-viewer, not part of what D1 moved server-side.
  const openProductIds = computed(() => products.value.filter((p) => p.is_active).map((p) => p.id))

  // Getters
  const hasProducts = computed(() => products.value.length > 0)
  const productCount = computed(() => products.value.length)
  const getProductById = computed(() => (id) => (id ? productsById.value[id] || null : null))
  // FE-9502c: ordered product objects for every open (shown) tab. Falls back
  // to the productsById cache so a tab survives even if `products` (the list
  // view's page) doesn't currently include it.
  const openProductTabs = computed(() =>
    openProductIds.value
      .map((id) => products.value.find((p) => p.id === id) || productsById.value[id] || null)
      .filter(Boolean),
  )
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
          // FE-9528: the Hub was the one product-scoped surface nothing re-scoped.
          await useCommHubStore().loadThreads({ product_id: productId })
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
    // FE-9528: the Hub was the one product-scoped surface nothing re-scoped.
    await useCommHubStore().loadThreads({ product_id: productId })

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

      // FE-9529: a deleted product's is_default is cleared server-side
      // (product_lifecycle_service.py's delete_product) -- if it WAS the
      // resolved default, re-read so the UI's notion of "where reads go"
      // doesn't keep pointing at a soft-deleted row until the next
      // focus/reconnect reconciliation happens to run.
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

  /**
   * FE-9529: set the tenant's DEFAULT product (where an unscoped read
   * resolves). Exactly one, DB-enforced (idx_product_single_default_per_tenant)
   * -- the backend clears any previous default in the SAME call
   * (ProductLifecycleService.set_default_product), so this never does a
   * separate clear-then-set that could leave a tenant with zero defaults.
   * Independent of shown/hidden: does not require or imply the target is
   * shown (D2 -- a hidden product is still a fully valid default).
   */
  async function setDefaultProduct(productId) {
    loading.value = true
    error.value = null
    try {
      const response = (await api.products?.setDefault(productId)) || { data: null }
      const updated = response.data
      if (updated) {
        // Mirror the server's single-default guarantee in the local list
        // immediately (don't wait on a full fetchProducts round trip):
        // the newly-default row gets the fresh object, every other row
        // that was previously flagged loses it.
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
      // The RESOLVED default (what the checkbox and any unscoped-read
      // display actually show) is a separate read -- refresh it rather than
      // assume the write response is what get_default_product would resolve.
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
      // Use dedicated default-product endpoint for accurate status
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
      // FE-9502c: product ids are UUID strings (src/giljo_mcp/models/products.py),
      // never numeric. The old `parseInt(storedProductId)` comparison here could
      // never match a real id, so a stored selection was silently discarded and
      // every reload fell back to products[0] -- reproduced as a failing test in
      // products.fe9502c.spec.js before this fix (museum rule). Plain string
      // comparison is the correct restore.
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

      // FE-9524/D1: one-time migration of FE-9502c's localStorage tab set into
      // server state. Runs only while the migration key still exists -- once
      // migrated it is removed, so a later session (this browser or another
      // machine) just reads the server's is_active flags via `openProductIds`
      // (computed, above) like any other product field.
      await migrateLocalTabsToServer()

      await fetchActiveProduct()
    } catch (error) {
      console.error('[PRODUCTS] Failed to initialize from storage:', error)
    }
  }

  /**
   * FE-9524/D1: one-shot migration of FE-9502c's localStorage tab set
   * (`openProductTabIds`) into server state (products.is_active). Runs at
   * most once per browser -- the key is removed after migrating, so a
   * re-login or a second device just sees the server's shown set already in
   * `products` (this browser having no local key at all lands here too, as a
   * no-op: nothing to migrate).
   */
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
    // The viewed tab must stay a real (shown) tab, same guarantee the old
    // localStorage restore made.
    if (currentProductId.value) {
      idsToShow.add(currentProductId.value)
    }

    const alreadyShown = new Set(openProductIds.value)
    const toActivate = [...idsToShow].filter((id) => !alreadyShown.has(id))
    if (toActivate.length > 0) {
      // FE-9529: each activate() call is its own request to
      // ProductLifecycleService.activate_product, which independently
      // guards the sole-shown-product default-fallback-erasure -- no
      // client-side promotion needed here even though this can batch
      // several activations from a legacy multi-tab localStorage set.
      await Promise.all(toActivate.map((id) => api.products?.activate(id)))
      await fetchProducts()
    }

    try {
      localStorage.removeItem('openProductTabIds')
    } catch {
      // localStorage unavailable -- nothing to clean up.
    }
  }

  /**
   * FE-9502c, server-backed since FE-9524/D1: show a product as a tab (server
   * write) and switch the viewed tab to it. A no-op re-show if already shown
   * (still switches). Additive: opening the FIRST tab for a fresh session
   * behaves exactly like the old single-product selection (setCurrentProduct
   * is the same call either way).
   */
  async function openTab(productId) {
    if (!productId) {
      return
    }
    if (!openProductIds.value.includes(productId)) {
      // FE-9529: the sole-shown-product default-fallback-erasure fix lives
      // in ProductLifecycleService.activate_product (the ONE owning writer
      // for "a product becomes shown" -- dual-door rule), not here, so any
      // caller of the REST/MCP surface gets the same guarantee this store
      // does. Nothing to do on this side beyond the existing activate call.
      await api.products?.activate(productId)
      await fetchProducts()
    }
    await switchTab(productId)
  }

  /** FE-9502c: switch the viewed tab. Tab-switch-refetch v1 (accepted per spec) -- routes through the existing setCurrentProduct so every reactive consumer refetches. */
  async function switchTab(productId) {
    await setCurrentProduct(productId)
  }

  /**
   * FE-9502c, server-backed since FE-9524/D1: hide a tab (server write).
   * Refuses to close the last remaining shown tab -- the tab strip must
   * always have at least one shown product when any product is shown.
   * Closing the viewed tab switches to its former neighbor.
   */
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
   * FE-9412, demoted by FE-9502c: refresh the DISPLAYED server-active product
   * against a dead/reconnecting socket.
   *
   * Pre-tabs, this also re-scoped the whole session via setCurrentProduct()
   * whenever the server's active product diverged -- correct when
   * currentProductId WAS the one product a session could ever be looking at.
   * Under the tabbed shell, currentProductId is the VIEWED TAB, a UI-local
   * choice; silently reassigning it from a background focus/reconnect event
   * would be exactly the auto-navigation ruling 3 forbids -- the user did not
   * click anything. So this now does ONLY the staleness-backstop half: keep
   * `activeProduct` (now just a display value / legacy-default, never
   * authoritative UI state) from going stale or blanking on a flaky read.
   * It never touches currentProductId or any open tab.
   */
  async function revalidateActiveProduct() {
    // This runs on every tab focus, so a flaky network must not be able to
    // blank the header: on a failed read, put back what was already there.
    const previousActive = activeProduct.value
    const read = await fetchActiveProduct()
    if (!read) {
      activeProduct.value = previousActive
    }
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
    openProductIds,
    openProductTabs,

    // Actions
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

    // WebSocket router handlers (0379a)
    handleProductMemoryUpdated,
    handleProductStatusChanged,
  }
})
