import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useJobsScopeStore = defineStore('jobsScope', () => {
  const allProducts = ref(true)

  function selectAll() {
    allProducts.value = true
  }

  function selectProduct() {
    allProducts.value = false
  }

  return { allProducts, selectAll, selectProduct }
})
