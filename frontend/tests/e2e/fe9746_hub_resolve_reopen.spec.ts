import { test, expect, Page, Locator } from '@playwright/test'
import { mkdirSync } from 'fs'

const EVIDENCE = process.env.FE9746_EVIDENCE_DIR || 'test-results/fe9746'
const RESOLVED_KEY = 'giljo.hub.threadList.resolvedOpen'

async function login(page: Page) {
  await page.goto('/login')
  await page.locator('[data-testid="email-input"] input').fill(process.env.TEST_USER!)
  await page.locator('[data-testid="password-input"] input').fill(process.env.TEST_PASSWORD!)
  await page.click('[data-testid="login-button"]')
  await page.waitForURL((u) => !u.pathname.includes('/login'), { timeout: 15000 })
}

async function pressCardControl(card: Locator) {
  await card.evaluate((el) => el.scrollIntoView({ block: 'center' }))
  await card.hover()
  const btn = card.getByTestId('thread-card-resolve')
  await btn.hover()
  await btn.click()
}

async function headers(page: Page) {
  const csrf = (await page.context().cookies()).find((c) => c.name === 'csrf_token')?.value ?? ''
  return { 'X-CSRF-Token': csrf, 'Content-Type': 'application/json' }
}

test.use({ actionTimeout: 10000 })

test('resolve a thread from its card, see it fold, reopen from the fold, and use the header control', async ({ page }) => {
  test.setTimeout(120000)
  mkdirSync(EVIDENCE, { recursive: true })
  await login(page)

  const products = await (await page.request.get('/api/v1/products/')).json()
  const list = Array.isArray(products) ? products : products.products || []
  const product = list.find((p: { is_active?: boolean }) => p.is_active) || list[0]
  const subject = `FE-9746 resolve check ${Date.now()}`
  const created = await page.request.post('/api/v1/threads', {
    headers: await headers(page),
    data: { subject, product_id: product?.id },
  })
  expect(created.ok()).toBeTruthy()
  const threadId = (await created.json()).thread_id as string

  try {
    await page.addInitScript((k) => localStorage.setItem(k, '1'), RESOLVED_KEY)
    await page.goto('/hub')
    await expect(page.getByTestId('thread-list')).toBeVisible()

    const openCard = page.getByTestId('thread-card').filter({ hasText: subject })
    await expect(openCard).toHaveCount(1)
    const resolvedSection = page.getByTestId('thread-list-resolved')
    await expect(resolvedSection.getByText(subject)).toHaveCount(0)

    await openCard.evaluate((el) => el.scrollIntoView({ block: 'center' }))
    await openCard.hover()
    await expect(openCard.getByTestId('thread-card-resolve')).toHaveAttribute('aria-label', 'Mark resolved')
    await page.waitForTimeout(400)
    await page.screenshot({ path: `${EVIDENCE}/1-card-hover-mark-resolved.png` })
    await pressCardControl(openCard)

    await expect(page.getByText('Thread resolved.')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Undo' })).toBeVisible()
    await expect(resolvedSection.getByText(subject)).toHaveCount(1)
    await page.screenshot({ path: `${EVIDENCE}/2-resolved-folded-with-undo-toast.png` })

    const foldedCard = resolvedSection.getByTestId('thread-card').filter({ hasText: subject })
    await foldedCard.evaluate((el) => el.scrollIntoView({ block: 'center' }))
    await foldedCard.hover()
    await expect(foldedCard.getByTestId('thread-card-resolve')).toHaveAttribute('aria-label', 'Reopen')
    await page.waitForTimeout(400)
    await page.screenshot({ path: `${EVIDENCE}/3-fold-card-hover-reopen.png` })
    await pressCardControl(foldedCard)
    await expect(page.getByText('Thread reopened.')).toBeVisible()
    await expect(resolvedSection.getByText(subject)).toHaveCount(0)
    await expect(page.getByTestId('thread-card').filter({ hasText: subject })).toHaveCount(1)

    await page.getByTestId('thread-card').filter({ hasText: subject }).click()
    const headerBtn = page.getByTestId('thread-header-resolve')
    await expect(headerBtn).toHaveAttribute('aria-label', 'Mark resolved')
    await headerBtn.click()
    await expect(headerBtn).toHaveAttribute('aria-label', 'Reopen')
    await page.screenshot({ path: `${EVIDENCE}/4-header-resolved-shows-reopen.png`, fullPage: true })
    await headerBtn.click()
    await expect(headerBtn).toHaveAttribute('aria-label', 'Mark resolved')
    await page.screenshot({ path: `${EVIDENCE}/5-header-reopened.png`, fullPage: true })
  } finally {
    await page.request.delete(`/api/v1/threads/${threadId}`, { headers: await headers(page) })
  }
})
