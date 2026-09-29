import { describe, it, expect, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useJobsScopeStore } from './jobsScope'

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('useJobsScopeStore', () => {
  it('lands on All', () => {
    const scope = useJobsScopeStore()
    expect(scope.allProducts).toBe(true)
  })

  it('a product tab narrows the board; All widens it again', () => {
    const scope = useJobsScopeStore()
    scope.selectProduct()
    expect(scope.allProducts).toBe(false)
    scope.selectAll()
    expect(scope.allProducts).toBe(true)
  })
})
