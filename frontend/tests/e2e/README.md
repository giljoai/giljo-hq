# Playwright E2E Tests

This directory contains end-to-end tests for the Giljo HQ frontend, focusing on critical user workflows including project staging, agent orchestration, and real-time WebSocket updates.

## Test Suite Overview

### launch-button-staging-complete.spec.js (Handover 0287)

Tests that the "Launch Jobs" button becomes enabled automatically after orchestrator staging completes, without requiring a page refresh.

**Key Test Cases:**

1. **launch_button_enables_after_staging_without_refresh**
   - Verifies the "Launch Jobs" button is initially disabled
   - Clicks "Stage Project" button
   - Waits for WebSocket events (mission_updated, agent:created)
   - Confirms button becomes enabled without page refresh
   - Validates button color changes from grey to yellow

2. **orchestrator_active_button_appears_after_staging**
   - Verifies stage button text changes from "Stage project" to "Orchestrator Active"
   - Confirms no page refresh during this state transition
   - Validates stage button becomes disabled

3. **launch_button_enables_with_agents_spawning**
   - Tests enabling logic with specialist agent spawning
   - Verifies button enables based on both mission AND agents presence
   - Validates real-time state updates

4. **staging_prompt_copied_to_clipboard**
   - Verifies clipboard notification after clicking stage
   - Confirms button loading state during prompt generation
   - Tests button functionality for retry scenarios

5. **websocket_events_trigger_button_update**
   - Monitors WebSocket traffic during staging
   - Verifies button state correlates with server events
   - Confirms no polling/manual refresh needed

### task_management.spec.js

Tests task creation, assignment, and conversion workflows.

## Prerequisites

### Environment Configuration

Set the Playwright test base URL via environment variable:

```bash
# Use default (http://localhost:7274)
npm run test:e2e

# Use custom URL
PLAYWRIGHT_TEST_BASE_URL=http://192.0.2.10:7274 npm run test:e2e
```

### Test User Credentials

Default test user (if using custom server):
- **Username:** `<your-username>` (set via `TEST_USER` env var)
- **Password:** `<your-test-password>` (set via `TEST_PASSWORD` env var)

### Project ID

For testing the launch-button-staging workflow, you'll need a valid project ID. The test uses:
- **Project ID:** 555d0207-4f30-498a-9c44-9904804270ee
- **URL:** `/projects/{PROJECT_ID}?via=jobs`

Create a new project if this ID doesn't exist, or update the test with your project ID.

## Running Tests

### Run All E2E Tests
```bash
cd frontend
npm run test:e2e
```

### Run Specific Test File
```bash
npm run test:e2e -- tests/e2e/launch-button-staging-complete.spec.js
```

### Run Specific Test Case
```bash
npm run test:e2e -- tests/e2e/launch-button-staging-complete.spec.js -g "launch_button_enables_after_staging"
```

### Run Tests with Custom URL
```bash
PLAYWRIGHT_TEST_BASE_URL=http://192.0.2.10:7274 npm run test:e2e
```

### Run Tests in Debug Mode
```bash
npm run test:e2e -- --debug
```

### Run Tests in UI Mode (Interactive)
```bash
npm run test:e2e -- --ui
```

### Run Tests with Video Recording
```bash
npm run test:e2e -- --headed  # Also records video on failure
```

### View Test Report
```bash
npm run test:e2e:report
```

## Expected Behavior

### Staging Workflow (Handover 0287)

1. **Initial State:**
   - "Stage project" button: enabled, yellow color
   - "Launch jobs" button: disabled, grey color

2. **After Clicking "Stage Project":**
   - Button enters loading state
   - Clipboard notification appears (prompt copied)
   - Orchestrator status fetched and stored in database

3. **After Orchestrator Starts (WebSocket Events):**
   - `project:mission_updated` event received
   - Store `orchestratorMission` field updated
   - `agent:created` events received for specialist agents
   - Store agents list populated

4. **Button State Changes:**
   - "Stage project" → "Orchestrator Active" (disabled)
   - "Launch jobs" → enabled (yellow color, clickable)
   - **No page refresh required**

5. **Ready to Launch:**
   - User can click "Launch jobs" immediately
   - Launches specialist agents (implementer, tester, etc.)
   - Navigates to Jobs tab to monitor progress

## WebSocket Event Flow

The staging process relies on WebSocket real-time updates:

```
┌─────────────────────────────────────────────────────────────┐
│ Frontend: Click "Stage Project"                              │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ Backend: Generate thin-client staging prompt                 │
│          Create orchestrator job in database                  │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ Frontend: Show clipboard notification                         │
└─────────────────────────────────────────────────────────────┘

[User copies prompt and runs in Claude Code CLI]

┌─────────────────────────────────────────────────────────────┐
│ Backend: Orchestrator agent receives staging prompt          │
│          Generates project mission                            │
│          Spawns specialist agents (implementer, tester)      │
└────────────────────┬────────────────────────────────────────┘
                     │
         ┌───────────┴──────────────┐
         │                          │
         ▼                          ▼
┌──────────────────────┐   ┌──────────────────────┐
│ WebSocket Event:     │   │ WebSocket Event:     │
│ mission_updated      │   │ agent:created        │
│ {mission: "..."}     │   │ {agent_type: "impl"} │
└────────┬─────────────┘   └────────┬─────────────┘
         │                          │
         │     ┌────────────────────┘
         │     │
         ▼     ▼
┌─────────────────────────────────────────────────────────────┐
│ Frontend: Update store                                        │
│           - Set orchestratorMission                          │
│           - Add agents to store.agents                       │
│           - Compute readyToLaunch = true                     │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ Frontend: Button State Changes                               │
│           - Stage button: "Orchestrator Active" (disabled)   │
│           - Launch button: enabled (yellow, clickable)       │
└─────────────────────────────────────────────────────────────┘
```

## Test Architecture

### Playwright Configuration

Located in `frontend/playwright.config.ts`:

```javascript
{
  timeout: 30000,           // 30 second test timeout
  baseURL: 'http://localhost:7274',
  screenshot: 'only-on-failure',
  video: 'retain-on-failure',
  trace: 'on-first-retry'
}
```

## Debugging Failed Tests

### Enable Video Recording
```bash
npm run test:e2e -- --headed
```

### Review Test Report
```bash
npm run test:e2e:report
```

### Common Issues

**Issue: "Launch jobs" button never enables**
- Verify WebSocket connection is open (browser DevTools > Network tab)
- Check console for WebSocket event errors
- Verify orchestrator job was created successfully
- Check that mission_updated event was received

**Issue: Page refresh occurs unexpectedly**
- Check for redirect loops in router guards
- Verify URL query parameters are preserved
- Review for accidental page reloads in event handlers

**Issue: Button state updates are slow**
- Check network latency to backend
- Review store update logic for debouncing
- Verify WebSocket message handler execution

**Issue: Tests timeout waiting for button state**
- Increase timeout in test configuration
- Add console logs to debug timing
- Verify backend is responding to requests
- Check for JavaScript errors in console

## Performance Expectations

| Action | Expected Duration |
|--------|-------------------|
| Stage Project button click | < 1 second (clipboard) |
| Orchestrator mission update (WebSocket) | 2-5 seconds |
| Specialist agent spawning (WebSocket) | 3-10 seconds |
| Launch button enabled | < 15 seconds total |
| Page refresh detection | < 100ms |

## Continuous Integration

For CI/CD environments, run tests headless:

```bash
npm run test:e2e -- --reporter=junit
```

Expected output:
```
test-results/junit.xml - JUnit XML report for CI/CD integration
playwright-report/ - HTML report with screenshots and videos
```

## Dependencies

- `@playwright/test` - E2E testing framework
- `vue` - Vue 3 components
- `vuetify` - UI component library
- `pinia` - State management

## Related Documentation

- **Handover 0287:** Launch button staging complete workflow
- **Handover 0289:** Message routing architecture fix
- **Handover 0290:** WebSocket payload normalization (fixes)
- **ProjectTabs.vue:** Button state logic and handlers
- **projectTabs.js:** Store readyToLaunch getter

## Contributing

When adding new E2E tests:

1. Create test file in `tests/e2e/` with `.spec.js` extension
2. Add shared helper utilities as a new file directly under `tests/e2e/` if needed
3. Document test scenarios in test comments
4. Use `data-testid` attributes for element selection (avoid brittle selectors)
5. Add logging via `TestLogger` for debugging
6. Test with multiple browsers (chromium, firefox, webkit)

## License

Giljo HQ - All rights reserved
