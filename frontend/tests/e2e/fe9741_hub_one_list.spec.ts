import { test, expect, Page } from '@playwright/test'
import { mkdirSync } from 'fs'

const EVIDENCE = process.env.FE9741_EVIDENCE_DIR || 'test-results/fe9741'
const SHOW_ALL_KEY = 'giljo.hub.threadList.showAll'
const RESOLVED_KEY = 'giljo.hub.threadList.resolvedOpen'

async function login(page: Page) {
  await page.goto('/login')
  await page.locator('[data-testid="email-input"] input').fill(process.env.TEST_USER!)
  await page.locator('[data-testid="password-input"] input').fill(process.env.TEST_PASSWORD!)
  await page.click('[data-testid="login-button"]')
  await page.waitForURL((u) => !u.pathname.includes('/login'), { timeout: 15000 })
}

async function headers(page: Page) {
  const csrf = (await page.context().cookies()).find((c) => c.name === 'csrf_token')?.value ?? ''
  return { 'X-CSRF-Token': csrf, 'Content-Type': 'application/json' }
}

test.use({ actionTimeout: 10000 })

test('hub shows one list: capped open threads, folded resolved, remembered choices', async ({ page }) => {
  test.setTimeout(120000)
  mkdirSync(EVIDENCE, { recursive: true })
  await login(page)

  const products = await (await page.request.get('/api/v1/products/')).json()
  const list = Array.isArray(products) ? products : products.products || []
  const product = list.find((p: { is_active?: boolean }) => p.is_active) || list[0]
  const subject = `FE-9741 resolved check ${Date.now()}`
  const created = await page.request.post('/api/v1/threads', {
    headers: await headers(page),
    data: { subject, product_id: product?.id },
  })
  expect(created.ok()).toBeTruthy()
  const threadId = (await created.json()).thread_id as string

  try {
    const resolved = await page.request.patch(`/api/v1/threads/${threadId}`, {
      headers: await headers(page),
      data: { status: 'resolved' },
    })
    expect(resolved.ok()).toBeTruthy()

    await page.addInitScript(
      ([a, b]) => {
        if (!sessionStorage.getItem('fe9741-cleared')) {
          localStorage.removeItem(a)
          localStorage.removeItem(b)
          sessionStorage.setItem('fe9741-cleared', '1')
        }
      },
      [SHOW_ALL_KEY, RESOLVED_KEY],
    )

    await page.goto('/hub')
    await expect(page.getByTestId('thread-list')).toBeVisible()

    await expect(page.getByTestId('hub-view').locator('[role="tablist"]')).toHaveCount(0)
    await expect(page.getByTestId('hub-tab-town')).toHaveCount(0)
    await expect(page.getByTestId('hub-tab-project')).toHaveCount(0)

    const cards = page.getByTestId('thread-card')
    await expect(cards).toHaveCount(5)
    const showAll = page.getByTestId('thread-list-show-all')
    await expect(showAll).toContainText(/^Show all \(\d+\)$/)
    const resolvedToggle = page.getByTestId('thread-list-resolved-toggle')
    await expect(resolvedToggle).toContainText('Resolved (')
    await expect(resolvedToggle).toHaveAttribute('aria-expanded', 'false')
    await page.waitForTimeout(1500)
    await expect(cards).toHaveCount(5)
    await page.screenshot({ path: `${EVIDENCE}/1-default-five-and-folded.png`, fullPage: true })

    await showAll.click()
    await expect(showAll).toHaveText('Show fewer')
    expect(await cards.count()).toBeGreaterThan(5)
    await page.reload()
    await expect(page.getByTestId('thread-list-show-all')).toHaveText('Show fewer')
    expect(await cards.count()).toBeGreaterThan(5)
    await page.getByTestId('thread-list-show-all').click()
    await expect(cards).toHaveCount(5)

    await resolvedToggle.click()
    await expect(resolvedToggle).toHaveAttribute('aria-expanded', 'true')
    await expect(page.getByTestId('thread-list-resolved').getByText(subject).first()).toBeVisible()
    await page.reload()
    await expect(page.getByTestId('thread-list-resolved-toggle')).toHaveAttribute('aria-expanded', 'true')
    await page.screenshot({ path: `${EVIDENCE}/2-resolved-open-remembered.png`, fullPage: true })
    await page.getByTestId('thread-list-resolved-toggle').click()
    await expect(page.getByTestId('thread-list-resolved-toggle')).toHaveAttribute('aria-expanded', 'false')

    await page.getByTestId('hub-search').locator('input').fill('FE-9741 resolved check')
    await expect(page.getByTestId('thread-list-resolved').getByText(subject).first()).toBeVisible()
    await expect(page.getByTestId('thread-list-show-all')).toHaveCount(0)
    await expect(page.locator('.thread-list .v-progress-circular')).toHaveCount(0)
    await page.screenshot({ path: `${EVIDENCE}/3-search-shows-resolved-hit.png`, fullPage: true })

    await page.goto(`/hub?thread=${threadId}&tab=project`)
    await expect(page.getByTestId('hub-back')).toBeVisible()
    await page.screenshot({ path: `${EVIDENCE}/4-deep-link-to-resolved-thread.png`, fullPage: true })
  } finally {
    await page.request.delete(`/api/v1/threads/${threadId}`, { headers: await headers(page) })
  }
})
