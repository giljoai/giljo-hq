# Giljo HQ Frontend Test Suite

## Overview

This test suite comprehensively validates the authentication and setup flow for the Giljo HQ frontend. The tests cover various scenarios including component interactions, integration flows, and end-to-end user journeys.

## Test Types

### 1. Unit Tests (`tests/unit/`)
- Focus on individual component behavior
- Test props, events, and internal logic
- Validate component rendering and interactions

### 2. Integration Tests (`tests/integration/`)
- Validate interactions between components and stores
- Test authentication flow and routing
- Verify WebSocket and API integrations

### 3. End-to-End Tests (`tests/e2e/`)
- Simulate complete user journeys
- Test from welcome screen to dashboard
- Validate responsive design and accessibility

## Key Test Scenarios

### Authentication Flow
- First-time setup password creation
- Login with new credentials
- Redirect to setup wizard
- Complete setup process

### Validation Checks
- Password strength requirements
- Form input validation
- Error handling
- Mobile responsiveness

## Running Tests

### Prerequisites
- Node.js 18+
- npm 8+
- Vue 3
- Vitest
- Cypress/Playwright

### Commands

```bash
# Run unit tests
npm run test:unit

# Run integration tests
npm run test:integration

# Run E2E tests
npm run test:e2e

# Generate coverage report
npm run test:coverage
```

## Test Coverage Goals

- Component Tests: 90%+ coverage
- Store Tests: 95%+ coverage
- Integration Tests: 80%+ coverage
- Critical User Flows: 100% coverage

## Debugging Tests

1. Use `vi.fn()` for mocking functions
2. Leverage `@vue/test-utils` for component testing
3. Check `vitest.config.js` for configuration details
4. Review `tests/setup.js` for global test configurations

## Troubleshooting

- Ensure all dependencies are installed
- Check browser compatibility
- Verify network mocking for API tests
- Validate Vuetify component interactions

## Contributing

1. Write tests before implementing features
2. Maintain clear, descriptive test names
3. Cover edge cases and error scenarios
4. Keep tests independent and isolated

## Contact

For questions or improvements, contact the frontend testing team.
