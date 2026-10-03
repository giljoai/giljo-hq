/**
 * fe9656_task_edit_sends_changed_fields.spec.ts — FE-9656
 *
 * The task edit dialog used to spread the whole task back to the server on
 * every save (useTaskCrud.saveTask), echoing every untouched field. This
 * locks the fix at the browser: the real PUT body observed on the wire for
 * each save, not just the composable's diff function in isolation. A green
 * Vitest suite already proved the diff logic is correct; it cannot prove the
 * dialog is wired to that logic, or that editSnapshot is seeded from the row
 * actually clicked (FE-9655c passed unit tests and was still broken twice,
 * found only by driving the real browser).
 *
 * The write path is `PUT /api/v1/tasks/{id}/` (not PATCH -- the backend also
 * registers a `@router.patch` alias, but useTaskCrud/api.js calls `.put()`).
 *
 * Edition scope: Both.
 */
import { test, expect, Page } from '@playwright/test'
import { loginAsDefaultTestUser, reportRateLimiting } from './helpers'

async function createTask(
  page: Page,
  title: string,
  options: { description?: string } = {},
): Promise<string> {
  await page.click('[data-testid="add-task-menu-btn"]')
  await page.click('[data-testid="new-task-menu-item"]')
  const dialog = page.locator('.v-dialog').filter({ has: page.locator('[data-test="edit-task-title"]') })
  await expect(dialog).toBeVisible()
  await dialog.locator('[data-test="edit-task-title"] input').fill(title)
  if (options.description) {
    await dialog.locator('[data-test="edit-task-description"] textarea').fill(options.description)
  }
  await dialog.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.locator('.v-dialog')).not.toBeVisible()

  // TasksTable tags the clickable title cell `task-row-{id}` -- read the id
  // back off it so the test can pin waitForRequest to this exact task's URL
  // rather than matching the first PUT to /tasks/ that comes along.
  const row = page.locator('tr', { hasText: title })
  await expect(row).toBeVisible()
  const rowContent = row.locator('[data-test^="task-row-"]')
  const testId = await rowContent.getAttribute('data-test')
  if (!testId) throw new Error(`createTask: no task-row-* data-test found for "${title}"`)
  return testId.replace('task-row-', '')
}

async function openEditDialog(page: Page, title: string) {
  const row = page.locator('tr', { hasText: title })
  await row.locator('.task-row-content').click()
  const dialog = page.locator('.v-dialog').filter({ has: page.locator('[data-test="edit-task-title"]') })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Save', exact: true })).toBeVisible()
  return dialog
}

/**
 * Match the update request for one specific task, whichever HTTP method the
 * app actually uses -- the test then asserts the observed method explicitly,
 * rather than baking an assumption into the predicate.
 */
function waitForTaskUpdateRequest(page: Page, taskId: string) {
  return page.waitForRequest(
    (req) =>
      req.url().includes(`/api/v1/tasks/${taskId}/`) &&
      (req.method() === 'PUT' || req.method() === 'PATCH'),
    { timeout: 10000 },
  )
}

test.describe('Task edit dialog sends only changed fields (FE-9656)', () => {
  test.beforeEach(async ({ page }) => {
    reportRateLimiting(page)
    await loginAsDefaultTestUser(page)
    await page.goto('/tasks')
    await page.waitForLoadState('networkidle')
  })

  test('one field changed (Status only) sends exactly that key', async ({ page }) => {
    const title = `E2E fe9656 status-only ${Date.now()}`
    const taskId = await createTask(page, title)
    const dialog = await openEditDialog(page, title)

    await dialog.locator('[data-test="edit-task-status"]').click()
    const [request] = await Promise.all([
      waitForTaskUpdateRequest(page, taskId),
      (async () => {
        await page.getByRole('option', { name: 'In Progress', exact: true }).click()
        await dialog.getByRole('button', { name: 'Save', exact: true }).click()
      })(),
    ])

    expect(request.method()).toBe('PUT')
    const body = request.postDataJSON()
    expect(body).toEqual({ status: 'in_progress' })
  })

  // FE-9675: an undecided task can be parked On hold. The server must accept
  // the value (it 422'd before FE-9675) and the row badge must show the label
  // the backend serves, not the raw value.
  test('picking On hold sends {"status": "on_hold"}, the server accepts it, and the badge reads On hold', async ({
    page,
  }) => {
    const title = `E2E fe9675 on-hold ${Date.now()}`
    const taskId = await createTask(page, title)
    const dialog = await openEditDialog(page, title)

    await dialog.locator('[data-test="edit-task-status"]').click()
    const [request, response] = await Promise.all([
      waitForTaskUpdateRequest(page, taskId),
      page.waitForResponse(
        (res) =>
          res.url().includes(`/api/v1/tasks/${taskId}/`) &&
          (res.request().method() === 'PUT' || res.request().method() === 'PATCH'),
        { timeout: 10000 },
      ),
      (async () => {
        await page.getByRole('option', { name: 'On hold', exact: true }).click()
        await dialog.getByRole('button', { name: 'Save', exact: true }).click()
      })(),
    ])

    expect(request.method()).toBe('PUT')
    expect(request.postDataJSON()).toEqual({ status: 'on_hold' })
    expect(response.status()).toBe(200)
    expect((await response.json()).status).toBe('on_hold')

    const row = page.locator('tr', { hasText: title })
    await expect(row.locator('.task-status-badge')).toHaveText('On hold')
  })

  test('two fields changed (Title and Priority) sends exactly those two -- never task_type, product_id or series_number', async ({
    page,
  }) => {
    const title = `E2E fe9656 two-fields ${Date.now()}`
    const newTitle = `${title} edited`
    const taskId = await createTask(page, title)
    const dialog = await openEditDialog(page, title)

    await dialog.locator('[data-test="edit-task-title"] input').fill(newTitle)
    await dialog.locator('[data-test="edit-task-priority"]').click()

    const [request] = await Promise.all([
      waitForTaskUpdateRequest(page, taskId),
      (async () => {
        await page.getByRole('option', { name: 'high', exact: true }).click()
        await dialog.getByRole('button', { name: 'Save', exact: true }).click()
      })(),
    ])

    expect(request.method()).toBe('PUT')
    const body = request.postDataJSON()
    expect(body).toEqual({ title: newTitle, priority: 'high' })
    // Explicit per FE-9656: these three are the exact fields the three
    // server-side guards exist to tolerate when a client echoes them back.
    // This client no longer should -- name them, don't just rely on toEqual.
    expect(body).not.toHaveProperty('task_type')
    expect(body).not.toHaveProperty('product_id')
    expect(body).not.toHaveProperty('series_number')
  })

  test('description cleared to an empty string sends {"description": ""} -- present, not omitted', async ({
    page,
  }) => {
    const title = `E2E fe9656 clear-description ${Date.now()}`
    // Seed a non-empty description at create time so clearing it in edit
    // mode is a genuine value -> '' transition, not a no-op diff (a fresh
    // task's description already defaults to '').
    const taskId = await createTask(page, title, { description: 'has real content' })
    const dialog = await openEditDialog(page, title)

    await dialog.locator('[data-test="edit-task-description"] textarea').fill('')

    const [request] = await Promise.all([
      waitForTaskUpdateRequest(page, taskId),
      dialog.getByRole('button', { name: 'Save', exact: true }).click(),
    ])

    expect(request.method()).toBe('PUT')
    const body = request.postDataJSON()
    // The regression this guards against: dropping a falsy value from the
    // diff entirely, which would silently fail to clear the field server-side.
    expect(body).toHaveProperty('description')
    expect(body.description).toBe('')
    expect(body).toEqual({ description: '' })
  })

  test('saving with no edits sends {} and the request still fires', async ({ page }) => {
    const title = `E2E fe9656 no-changes ${Date.now()}`
    const taskId = await createTask(page, title)
    const dialog = await openEditDialog(page, title)

    // FE-9656 decision: an unedited save still calls the API with an empty
    // patch. An empty PUT still round-trips the server's authorization check
    // (api/endpoints/tasks.py:385-388), so an expired session or a revoked
    // permission fails honestly; skipping the request client-side would show
    // "saved" without ever contacting the server. Pinned here so a future
    // change cannot quietly flip it without a red test.
    const [request] = await Promise.all([
      waitForTaskUpdateRequest(page, taskId),
      dialog.getByRole('button', { name: 'Save', exact: true }).click(),
    ])

    expect(request.method()).toBe('PUT')
    const body = request.postDataJSON()
    expect(body).toEqual({})
  })
})
