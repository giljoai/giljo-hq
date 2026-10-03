/**
 * E2E Test Helpers
 *
 * Shared utilities for Playwright E2E tests: authentication, test data
 * management and an MCP client.
 */

import { Page, APIRequestContext } from '@playwright/test'

// ============================================
// CONFIGURATION
// ============================================

const API_BASE_URL = 'http://localhost:7272'

// The API applies a per-IP limiter (API_RATE_LIMIT, 300 requests/minute by
// default). One login plus one list view costs roughly 33 API calls, so a
// handful of back-to-back spec runs saturates it. A throttled run does not
// announce itself: the 429 surfaces as an empty list, a missing row or a
// detached element, which reads like a product fault. Name it instead.
const RATE_LIMIT_HINT =
  '(the API per-IP rate limit is saturated -- space the runs about a minute apart, ' +
  'or start the backend with DISABLE_RATE_LIMIT=true)'

// ============================================
// AUTHENTICATION HELPERS
// ============================================

const DEFAULT_TEST_USER = process.env.TEST_USER || ''
const DEFAULT_TEST_PASSWORD = process.env.TEST_PASSWORD || ''

/**
 * Login as a test user
 *
 * CRITICAL: Verifies httpOnly cookie is set after successful login.
 * The backend sets 'access_token' cookie with httpOnly=true, secure=false, samesite=lax.
 *
 * @param page - Playwright page instance
 * @param email - User email (default: TEST_USER env var)
 * @param password - User password (default: TEST_PASSWORD env var)
 */
async function loginAsTestUser(
  page: Page,
  email: string = DEFAULT_TEST_USER,
  password: string = DEFAULT_TEST_PASSWORD
): Promise<void> {
  if (!email || !password) {
    throw new Error(
      'Test credentials missing: set TEST_USER and TEST_PASSWORD env vars (or pass email/password explicitly)'
    )
  }
  console.log('[loginAsTestUser] Starting login process...')

  // Navigate to login page
  await page.goto('http://localhost:7274/login')
  await page.waitForLoadState('networkidle')

  const emailInput = page.locator('[data-testid="email-input"] input')
  const passwordInput = page.locator('[data-testid="password-input"] input')

  await emailInput.fill(email)
  await passwordInput.fill(password)
  await page.click('[data-testid="login-button"]')

  // Wait for post-login redirect (backend redirects to / which Vue Router handles)
  // The URL should change from /login to something else (/, /dashboard, or /projects)
  await page.waitForURL((url) => {
    const urlObj = new URL(url)
    return !urlObj.pathname.includes('/login')
  }, { timeout: 10000 })

  await page.waitForLoadState('networkidle')

  // Wait a bit more to ensure httpOnly cookie is fully set
  await page.waitForTimeout(500)

  // CRITICAL: Verify auth cookie was set by backend
  console.log('[loginAsTestUser] Verifying auth cookie was set...')
  const cookies = await page.context().cookies()
  const authCookie = cookies.find(c => c.name === 'access_token')

  if (!authCookie) {
    console.error('[loginAsTestUser] FAILED: No access_token cookie found after login!')
    console.error('[loginAsTestUser] Available cookies:', cookies.map(c => c.name))
    throw new Error('Login failed: No access_token cookie found')
  }

  console.log('[loginAsTestUser] SUCCESS: Auth cookie verified:', {
    name: authCookie.name,
    domain: authCookie.domain,
    path: authCookie.path,
    httpOnly: authCookie.httpOnly,
    sameSite: authCookie.sameSite,
    secure: authCookie.secure,
    valueLength: authCookie.value.length
  })

  console.log('[loginAsTestUser] Login successful, current URL:', page.url())
}

/**
 * Login as default test user (uses TEST_USER and TEST_PASSWORD env vars)
 */
/**
 * FE-9685: the Jobs board opens Compact (every card folded) in a fresh browser.
 * Specs that drive an open card's controls call this before the first page
 * load so the board opens under Detailed, the way a user who picked it sees it.
 */
export async function openBoardCardsDetailed(page: Page): Promise<void> {
  await page.addInitScript(() => window.localStorage.setItem('jobs.density.v2', 'detailed'))
}

export async function loginAsDefaultTestUser(page: Page): Promise<void> {
  await loginAsTestUser(page)
}

// ============================================
// TEST DATA HELPERS
// ============================================

/**
 * Create a test project via API
 *
 * @param page - Playwright page instance
 * @param projectData - Project data (name, description)
 * @returns Project ID
 */
export async function createTestProject(
  page: Page,
  projectData: { name?: string; description?: string; product_id?: string } = {}
): Promise<string> {
  const token = await getAuthToken(page)
  const csrf = (await page.context().cookies()).find((c) => c.name === 'csrf_token')?.value ?? ''

  let productId = projectData.product_id
  if (!productId) {
    const productsResponse = await page.request.get(`${API_BASE_URL}/api/v1/products/`, {
      headers: { 'Authorization': `Bearer ${token}` },
    })
    // Report the status before parsing. A throttled lookup (429) returns a body
    // with no products, which used to surface as "the test user has no product"
    // and sent readers hunting for a data problem that was never there.
    if (!productsResponse.ok()) {
      throw new Error(
        `Failed to create test project: product lookup returned ${productsResponse.status()}` +
          (productsResponse.status() === 429 ? ` ${RATE_LIMIT_HINT}` : '')
      )
    }
    const body = await productsResponse.json()
    const products: Array<{ id: string; is_active?: boolean }> = Array.isArray(body) ? body : body.products ?? []
    productId = (products.find((p) => p.is_active) ?? products[0])?.id
    if (!productId) throw new Error('Failed to create test project: the test user has no product')
  }

  const response = await page.request.post(`${API_BASE_URL}/api/v1/projects/`, {
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json',
      'X-CSRF-Token': csrf,
    },
    data: {
      name: projectData.name || `E2E Test Project ${Date.now()}`,
      description: projectData.description || 'Automated E2E test project',
      product_id: productId,
    },
  })

  if (!response.ok()) {
    throw new Error(
      `Failed to create test project: ${response.status()}` +
        (response.status() === 429 ? ` ${RATE_LIMIT_HINT}` : '')
    )
  }

  const data = await response.json()
  return data.id
}

/**
 * Delete a test project via API
 *
 * @param page - Playwright page instance
 * @param projectId - Project ID to delete
 */
export async function deleteTestProject(
  page: Page,
  projectId: string
): Promise<void> {
  const token = await getAuthToken(page)
  const csrf = (await page.context().cookies()).find((c) => c.name === 'csrf_token')?.value ?? ''

  await page.request.delete(`${API_BASE_URL}/api/v1/projects/${projectId}`, {
    headers: {
      'Authorization': `Bearer ${token}`,
      'X-CSRF-Token': csrf,
    },
  })
}

/**
 * Get authentication token from page context
 *
 * The backend stores the JWT token in an httpOnly cookie named 'access_token'.
 * We retrieve it from the browser's cookie store instead of localStorage.
 *
 * @param page - Playwright page instance
 * @returns JWT token
 */
async function getAuthToken(page: Page): Promise<string> {
  // Get cookies from the browser context
  const cookies = await page.context().cookies()

  // Find the access_token httpOnly cookie
  const authCookie = cookies.find(cookie => cookie.name === 'access_token')

  if (!authCookie || !authCookie.value) {
    throw new Error('No auth token found in page context (httpOnly cookie "access_token" not found)')
  }

  return authCookie.value
}

/**
 * Log every throttled response so a rate-limited run says so in the output.
 *
 * Call from a spec's beforeEach. See RATE_LIMIT_HINT above for why.
 *
 * @param page - Playwright page instance
 */
export function reportRateLimiting(page: Page): void {
  page.on('response', (response) => {
    if (response.status() === 429) {
      console.warn(`[e2e] 429 ${response.request().method()} ${response.url()} ${RATE_LIMIT_HINT}`)
    }
  })
}

/** JSON headers for a REST call as the logged-in user (JWT + CSRF). */
export async function authHeaders(page: Page): Promise<Record<string, string>> {
  const token = await getAuthToken(page)
  const csrf = (await page.context().cookies()).find((c) => c.name === 'csrf_token')?.value ?? ''
  return { Authorization: `Bearer ${token}`, 'X-CSRF-Token': csrf, 'Content-Type': 'application/json' }
}

/** Minimal streamable-HTTP MCP client: initialize once, then tools/call. */
export class McpClient {
  private sessionId = ''
  private version = '2025-06-18'
  private nextId = 1

  constructor(private request: APIRequestContext, private apiKey: string) {}

  private async rpc(method: string, params: object, notification = false) {
    const headers: Record<string, string> = {
      'X-API-Key': this.apiKey,
      'Content-Type': 'application/json',
      Accept: 'application/json, text/event-stream',
    }
    if (this.sessionId) headers['mcp-session-id'] = this.sessionId
    if (method !== 'initialize') headers['mcp-protocol-version'] = this.version
    const body = notification ? { jsonrpc: '2.0', method, params } : { jsonrpc: '2.0', id: this.nextId++, method, params }
    const res = await this.request.post(`${API_BASE_URL}/mcp`, { headers, data: body })
    if (!res.ok() && res.status() !== 202) throw new Error(`MCP ${method} failed: ${res.status()} ${await res.text()}`)
    const sid = res.headers()['mcp-session-id']
    if (sid) this.sessionId = sid
    if (notification) return null
    const text = await res.text()
    const json = text.trim().startsWith('{')
      ? JSON.parse(text)
      : JSON.parse(text.split('\n').filter((l) => l.startsWith('data:')).pop()!.slice(5))
    if (json.error) throw new Error(`MCP ${method} error: ${JSON.stringify(json.error)}`)
    return json.result
  }

  async init() {
    const result = await this.rpc('initialize', {
      protocolVersion: this.version,
      capabilities: {},
      clientInfo: { name: 'e2e-helpers', version: '1.0' },
    })
    this.version = result?.protocolVersion || this.version
    await this.rpc('notifications/initialized', {}, true)
  }

  async tool(name: string, args: object) {
    const result = await this.rpc('tools/call', { name, arguments: args })
    if (result?.isError) throw new Error(`${name}: ${JSON.stringify(result.content)}`)
    if (result?.structuredContent) return result.structuredContent
    const text = result?.content?.[0]?.text
    return text ? JSON.parse(text) : result
  }
}
