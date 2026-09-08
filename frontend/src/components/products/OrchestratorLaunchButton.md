# OrchestratorLaunchButton Component

Production-grade Vue 3 component for launching multi-agent orchestration
workflows with real-time WebSocket progress tracking.

## Overview

The `OrchestratorLaunchButton` component provides a complete user interface for
launching the Giljo HQ orchestrator, including:

- Intelligent button state management (enabled/disabled based on product status)
- Real-time progress tracking via WebSocket events
- Visual timeline of workflow stages
- Comprehensive error handling and recovery
- Full accessibility support (WCAG 2.1 AA compliant)
- Screen reader announcements for progress updates

## Props

| Prop      | Type   | Required | Description                                                              |
| --------- | ------ | -------- | ------------------------------------------------------------------------ |
| `product` | Object | Yes      | Product object with `id`, `is_active`, `has_vision_documents` properties |

### Product Object Structure

```javascript
{
  id: "uuid-string",              // Product UUID
  is_active: true,                // Whether product is currently active
  has_vision_documents: true,     // Whether product has uploaded vision docs
  name: "Product Name"            // Product name (optional, for display)
}
```

## Events

| Event      | Payload                                | Description                                      |
| ---------- | -------------------------------------- | ------------------------------------------------ |
| `launched` | `{ session_id, workflow_result, ... }` | Emitted when orchestrator successfully completes |
| `error`    | `{ stage, error, details }`            | Emitted when orchestrator launch fails           |

## Usage

### Basic Usage

```vue
<template>
  <OrchestratorLaunchButton
    :product="currentProduct"
    @launched="handleLaunched"
    @error="handleError"
  />
</template>

<script setup>
import { ref } from 'vue'
import OrchestratorLaunchButton from '@/components/products/OrchestratorLaunchButton.vue'

const currentProduct = ref({
  id: 'prod-123',
  is_active: true,
  has_vision_documents: true,
  name: 'My Product',
})

function handleLaunched(data) {
  console.log('Orchestrator launched successfully:', data)
  // Navigate to project view, show success message, etc.
}

function handleError(error) {
  console.error('Orchestrator launch failed:', error)
  // Show error notification
}
</script>
```

### In Product Detail View

```vue
<template>
  <v-container>
    <v-card>
      <v-card-title>{{ product.name }}</v-card-title>

      <v-card-text>
        <!-- Product information -->
      </v-card-text>

      <v-card-actions>
        <v-spacer></v-spacer>
        <OrchestratorLaunchButton
          :product="product"
          @launched="navigateToProject"
          @error="showErrorNotification"
        />
      </v-card-actions>
    </v-card>
  </v-container>
</template>

<script setup>
import { useRouter } from 'vue-router'
import OrchestratorLaunchButton from '@/components/products/OrchestratorLaunchButton.vue'
import { useToast } from '@/composables/useToast'

const router = useRouter()
const { showToast } = useToast()

const props = defineProps({
  product: {
    type: Object,
    required: true,
  },
})

function navigateToProject(data) {
  showToast({
    type: 'success',
    message: `Orchestrator launched! Project ID: ${data.project_id}`,
    timeout: 5000,
  })

  // Navigate to project view
  router.push(`/projects/${data.project_id}`)
}

function showErrorNotification(error) {
  showToast({
    type: 'error',
    message: error.error || 'Failed to launch orchestrator',
    timeout: 8000,
  })
}
</script>
```

## WebSocket Events

The component listens for two WebSocket event types:

### 1. Progress Updates (`orchestrator:progress`)

Broadcasted during workflow execution to show real-time progress.

**Event Structure:**

```javascript
{
  type: "orchestrator:progress",
  data: {
    session_id: "uuid",
    product_id: "uuid",
    stage: "generating_missions",
    progress: 40,              // 0-100
    message: "Generating condensed missions...",
    details: {                 // Optional
      mission_count: 5
    },
    timestamp: "2025-10-28T10:30:00Z"
  }
}
```

**Stages:**

- `starting` (0%) - Initializing orchestrator
- `processing_vision` (20%) - Processing vision documents
- `generating_missions` (40%) - Generating mission plan
- `selecting_agents` (60%) - Selecting optimal agents
- `creating_workflow` (80%) - Coordinating workflow
- `complete` (100%) - Orchestrator launched

### 2. Error Events (`orchestrator:error`)

Broadcasted when orchestrator encounters an error.

**Event Structure:**

```javascript
{
  type: "orchestrator:error",
  data: {
    session_id: "uuid",
    product_id: "uuid",
    stage: "validation",
    error: "Product is not active",
    details: {                 // Optional
      hint: "Activate the product in the Products view"
    },
    timestamp: "2025-10-28T10:30:00Z"
  }
}
```

## UI States

### 1. Enabled State

- Product is active
- Product has vision documents
- Button is clickable with primary color
- Tooltip: "Launch multi-agent orchestration workflow"

### 2. Disabled State (Inactive Product)

- Product is not active
- Button is disabled (greyed out)
- Tooltip: "Product must be active"

### 3. Disabled State (No Vision Documents)

- Product has no vision documents uploaded
- Button is disabled (greyed out)
- Tooltip: "Product must have vision documents"

### 4. Loading State

- Button shows loading spinner
- Progress dialog is open
- Real-time stage updates displayed

### 5. Complete State

- Progress dialog shows 100% complete
- Success message displayed
- "Close" button enabled
- Green success styling

### 6. Error State

- Progress dialog shows error alert
- Error message displayed
- "Close" and "Retry" buttons enabled
- Red error styling

## Progress Dialog Features

### Progress Bar

- Visual representation of workflow progress (0-100%)
- Indeterminate mode during initialization
- Color-coded: blue (in progress), green (complete), red (error)

### Stage Timeline

- Visual timeline of completed and active stages
- Check mark icons for completed stages
- Spinner for active stage
- Only shows completed stages and current stage (clean progressive disclosure)

### Expandable Details Panel

- Shows additional information when available
- Automatically formats detail keys (snake_case to Title Case)
- Only visible when details are present

### Error Alert

- Red alert box with error message
- Retry button for recovery
- Clear, actionable error messages

## Accessibility Features

### WCAG 2.1 AA Compliance

1. **Keyboard Navigation**
   - Full keyboard support (Tab, Enter, Escape)
   - Focus indicators on all interactive elements
   - Dialog can be closed with Escape key

2. **Screen Reader Support**
   - ARIA labels on all interactive elements
   - Live region announcements for progress updates
   - Descriptive button labels and tooltips
   - Progress bar labeled with current percentage

3. **Color Contrast**
   - All text meets WCAG AA contrast requirements (4.5:1 minimum)
   - Status colors (success/error) supplemented with icons
   - No information conveyed by color alone

4. **Focus Management**
   - Focus trapped in dialog during progress
   - Focus returns to trigger button on close
   - Logical tab order maintained

## API Integration

The component uses the `api.orchestrator.launch()` endpoint:

**Request:**

```javascript
{
  product_id: "uuid",
  project_description: "Generated from product vision documents",
  workflow_type: "waterfall",  // or "parallel"
  auto_start: true
}
```

**Response:**

```javascript
{
  success: true,
  session_id: "uuid",
  workflow_result: { ... },
  mission_count: 5,
  agent_count: 3,
  project_id: "uuid",
  token_reduction: { ... }
}
```

**Error Codes:**

- `400` - Invalid request data
- `404` - Product not found
- `409` - Product not active or missing vision documents
- `500` - Internal orchestrator error

## Performance Considerations

1. **WebSocket Cleanup**
   - Event listeners registered on component mount
   - Listeners cleaned up on component unmount
   - Prevents memory leaks in long-running sessions

2. **Session Filtering**
   - Only processes WebSocket events for current session
   - Prevents cross-contamination between multiple launches

3. **Progressive Disclosure**
   - Timeline only shows completed stages + current stage
   - Details panel collapsible by default
   - Reduces visual clutter during workflow

## Error Handling

The component handles multiple error scenarios:

1. **Product Validation Errors** (409)
   - Inactive product
   - Missing vision documents
   - Shows hint for resolution

2. **Not Found Errors** (404)
   - Product doesn't exist
   - Clear error message

3. **Network Errors**
   - Connection timeout
   - Server unavailable
   - Retry option provided

4. **WebSocket Errors**
   - Connection lost during workflow
   - Progress updates fail gracefully
   - User informed of disconnection

## Testing

### Unit Tests (Recommended)

```javascript
import { mount } from '@vue/test-utils'
import { describe, it, expect, vi } from 'vitest'
import OrchestratorLaunchButton from './OrchestratorLaunchButton.vue'

describe('OrchestratorLaunchButton', () => {
  it('renders button with correct label', () => {
    const wrapper = mount(OrchestratorLaunchButton, {
      props: {
        product: {
          id: 'test-id',
          is_active: true,
          has_vision_documents: true,
        },
      },
    })

    expect(wrapper.text()).toContain('Launch Orchestrator')
  })

  it('disables button when product is inactive', () => {
    const wrapper = mount(OrchestratorLaunchButton, {
      props: {
        product: {
          id: 'test-id',
          is_active: false,
          has_vision_documents: true,
        },
      },
    })

    const button = wrapper.find('button')
    expect(button.attributes('disabled')).toBeDefined()
  })

  it('emits launched event on successful completion', async () => {
    // Test implementation
  })
})
```

### Manual Testing Checklist

- [ ] Button is enabled for active product with vision documents
- [ ] Button is disabled for inactive product
- [ ] Button is disabled for product without vision documents
- [ ] Progress dialog opens on button click
- [ ] Progress updates received via WebSocket
- [ ] Timeline shows completed stages with check marks
- [ ] Current stage shows spinner
- [ ] Details panel expands/collapses correctly
- [ ] Error alert shows on failure
- [ ] Retry button works after error
- [ ] Close button only enabled when complete/error
- [ ] Dialog cannot be dismissed during progress
- [ ] Keyboard navigation works (Tab, Enter, Escape)
- [ ] Screen reader announces progress updates
- [ ] Tooltips show correct messages for each state

## Troubleshooting

### Button Always Disabled

**Solution:** Verify product object has correct properties:

```javascript
console.log('Product:', product)
console.log('Is Active:', product.is_active)
console.log('Has Vision:', product.has_vision_documents)
```

### No Progress Updates

**Solution:** Check WebSocket connection:

```javascript
import websocketService from '@/services/websocket'

console.log('WebSocket State:', websocketService.getState())
console.log('WebSocket Connection:', websocketService.getConnectionInfo())
```

### API Errors

**Solution:** Check network tab for request/response:

- Verify endpoint URL is correct: `/api/v1/orchestration/launch`
- Check request payload has all required fields
- Verify tenant key is included in headers

### Memory Leaks

**Solution:** Ensure component is properly unmounted:

- WebSocket listeners should be cleaned up
- Check browser DevTools Performance tab
- Look for increasing event listener count

## Best Practices

1. **Always Handle Events**
   - Listen to both `launched` and `error` events
   - Provide user feedback for all outcomes

2. **Validate Product State**
   - Check product is active before rendering component
   - Verify vision documents exist
   - Show clear error messages if requirements not met

3. **WebSocket Connection**
   - Ensure WebSocket is connected before launching
   - Handle connection loss gracefully
   - Provide reconnection feedback to user

4. **User Feedback**
   - Show success notification on completion
   - Navigate to project view after launch
   - Provide actionable error messages

5. **Accessibility**
   - Always include ARIA labels
   - Test with keyboard navigation
   - Verify screen reader compatibility

## Related Components

- `ProductCard.vue` - Product list/grid display
- `ProjectView.vue` - Project detail view (navigation target)

## API Dependencies

- `/api/v1/orchestration/launch` - Launch orchestrator endpoint
- WebSocket events: `orchestrator:progress`, `orchestrator:error`
- `api.orchestrator.launch()` - API service method

## Version History

- **v1.0.0** (2025-10-28) - Initial production release
  - Complete orchestrator launch workflow
  - Real-time WebSocket progress tracking
  - Full accessibility support
  - Comprehensive error handling
