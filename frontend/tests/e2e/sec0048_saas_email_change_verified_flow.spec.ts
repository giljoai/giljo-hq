/**
 * sec0048_saas_email_change_verified_flow.spec.ts — SEC-0048
 *
 * Hosted edition only. An account email must change only through the verified
 * flow: Save on the Profile page asks for a confirmation link to the NEW address
 * (POST /api/saas/email-change/request) and never sends `email` on the generic
 * PUT /api/v1/users/{id}. The server refuses that generic write too, and the
 * stored address stays put until the link is confirmed.
 *
 * Run against a SaaS-mode backend with E2E_EDITION=saas (skipped otherwise).
 * Cleans up after itself: the pending change is cancelled at the end.
 *
 * Edition scope: SaaS.
 */
import { test, expect, Page } from '@playwright/test'
import { loginAsDefaultTestUser, reportRateLimiting } from './helpers'

test.skip(process.env.E2E_EDITION !== 'saas', 'Hosted-edition flow: set E2E_EDITION=saas')

async function openProfile(page: Page) {
  await page.goto('/account/profile')
  await page.waitForLoadState('networkidle')
  await expect(page.locator('[data-test="email-field"] input')).toBeVisible()
}

test.describe('Hosted email change goes through verification (SEC-0048)', () => {
  test.beforeEach(async ({ page }) => {
    reportRateLimiting(page)
    await loginAsDefaultTestUser(page)
  })

  test('Profile Save requests a verification link and never PUTs the email', async ({ page }) => {
    await openProfile(page)
    const emailInput = page.locator('[data-test="email-field"] input')
    const originalEmail = await emailInput.inputValue()
    const newEmail = `sec0048-e2e-${Date.now()}@example.com`

    const userPutBodies: string[] = []
    page.on('request', (req) => {
      if (req.method() === 'PUT' && req.url().includes('/api/v1/users/'))
        userPutBodies.push(req.postData() ?? '')
    })
    const verifyRequest = page.waitForRequest(
      (req) => req.method() === 'POST' && req.url().includes('/api/saas/email-change/request'),
      { timeout: 10000 },
    )

    await emailInput.fill(newEmail)
    await page.locator('[data-test="save-profile-btn"]').click()

    const sent = await verifyRequest
    expect(JSON.parse(sent.postData() ?? '{}').new_email).toBe(newEmail)
    await expect(page.locator('[data-test="email-pending-banner"]')).toContainText(newEmail)
    for (const body of userPutBodies) expect(body).not.toContain('"email"')
    await expect(emailInput).toHaveValue(originalEmail)

    await page.locator('[data-test="email-cancel-btn"]').click()
    await expect(page.locator('[data-test="email-pending-banner"]')).toHaveCount(0)
  })

  test('the generic user update refuses a new email from a signed-in browser', async ({ page }) => {
    await openProfile(page)
    const originalEmail = await page.locator('[data-test="email-field"] input').inputValue()

    const result = await page.evaluate(async () => {
      const me = await (await fetch('/api/auth/me', { credentials: 'include' })).json()
      const csrf =
        document.cookie
          .split('; ')
          .find((c) => c.startsWith('csrf_token='))
          ?.split('=')[1] ?? ''
      const res = await fetch(`/api/v1/users/${me.id}`, {
        method: 'PUT',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
        body: JSON.stringify({ email: `sec0048-direct-${Date.now()}@example.com` }),
      })
      return { status: res.status, body: await res.text() }
    })

    expect(result.status).toBe(400)
    expect(result.body.toLowerCase()).toContain('verification')

    await openProfile(page)
    await expect(page.locator('[data-test="email-field"] input')).toHaveValue(originalEmail)
  })
})
