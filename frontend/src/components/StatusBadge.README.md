# StatusBadge Component

A reusable Vue 3 component for displaying and managing project status with an
interactive dropdown menu.

## Features

- Interactive status badge with click-to-expand menu
- Context-aware actions based on current status
- Confirmation dialogs for destructive actions
- Loading states during API operations
- Full keyboard navigation support
- WCAG 2.1 AA accessible
- Professional Vuetify 3 design

## Usage

### Basic Implementation

```vue
<template>
  <StatusBadge
    :status="project.status"
    :project-id="project.id"
    :project-name="project.name"
    @action="handleStatusAction"
  />
</template>

<script setup>
import { ref } from 'vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { useToast } from '@/composables/useToast'
import api from '@/services/api'

const { showToast } = useToast()

const handleStatusAction = async ({ action, newStatus, projectId }) => {
  try {
    if (action === 'delete') {
      // Handle delete action
      await api.projects.delete(projectId)
      showToast({
        message: 'Project deleted successfully',
        type: 'success',
        duration: 3000,
      })
      // Refresh project list or navigate away
      return
    }

    // Handle status updates
    await api.projects.update(projectId, { status: newStatus })

    showToast({
      message: `Project status updated to ${newStatus}`,
      type: 'success',
      duration: 3000,
    })

    // Refresh project data
    await loadProjects()
  } catch (error) {
    console.error('Failed to update project status:', error)
    showToast({
      message: 'Failed to update project status',
      type: 'error',
      duration: 5000,
    })
  }
}
</script>
```

### Props

| Prop          | Type   | Required | Default          | Description                                                                                                  |
| ------------- | ------ | -------- | ---------------- | ------------------------------------------------------------------------------------------------------------ |
| `status`      | String | Yes      | -                | Current project status. Must be one of: `inactive`, `active`, `completed`, `cancelled`, `archived` |
| `projectId`   | String | Yes      | -                | Unique project identifier for API calls                                                                      |
| `projectName` | String | No       | `'this project'` | Project name used in confirmation dialogs                                                                    |

### Events

| Event      | Payload                                                    | Description                                                                    |
| ---------- | ---------------------------------------------------------- | ------------------------------------------------------------------------------ |
| `@action`  | `{ action: string, newStatus: string, projectId: string }` | Emitted when user selects an action. Parent component should handle API calls. |
| `@loading` | `{ loading: boolean }`                                     | Emitted when loading state changes (action starts/completes)                   |
| `@error`   | `{ error: string }`                                        | Reserved for future error handling                                             |

### Status Colors

| Status    | Color     | Hex     | Icon               |
| --------- | --------- | ------- | ------------------ |
| active    | Green     | #4CAF50 | mdi-play-circle    |
| inactive  | Grey      | #9E9E9E | mdi-circle-outline |
| completed | Blue      | #2196F3 | mdi-check-circle   |
| cancelled | Red       | #F44336 | mdi-cancel         |
| archived  | Dark Grey | -       | mdi-archive        |

### Available Actions by Status

| Current Status | Available Actions                                  |
| -------------- | -------------------------------------------------- |
| inactive       | Activate, Complete, Cancel, Archive, Delete        |
| active         | Complete, Cancel, Deactivate, Delete               |
| completed      | Reopen, Archive, Delete                            |
| cancelled      | Reopen, Archive, Delete                            |
| archived       | Restore, Delete                                    |

### Action Behavior

**Non-Destructive Actions** (no confirmation):

- Activate, Deactivate, Reopen, Restore

**Requires Confirmation**:

- Complete, Archive

**Destructive Actions** (requires confirmation with warning):

- Cancel, Delete

## Accessibility Features

- Full keyboard navigation (Tab, Enter, Space, Escape)
- ARIA labels on all interactive elements
- Clear focus indicators (2px outline)
- Screen reader compatible
- Role attributes for semantic HTML
- Color contrast compliance (WCAG AA)

### Keyboard Shortcuts

| Key           | Action                   |
| ------------- | ------------------------ |
| Tab           | Navigate to badge        |
| Enter/Space   | Open/close dropdown menu |
| Arrow Up/Down | Navigate menu items      |
| Enter         | Select menu item         |
| Escape        | Close menu/dialog        |

## Integration with ProjectsView

```vue
<!-- In ProjectsView.vue -->
<template>
  <v-data-table :items="projects">
    <template #item.status="{ item }">
      <StatusBadge
        :status="item.status"
        :project-id="item.id"
        :project-name="item.name"
        @action="handleStatusAction"
      />
    </template>
  </v-data-table>
</template>
```

## Advanced Usage

### Manual Loading Control

```vue
<template>
  <StatusBadge
    ref="statusBadgeRef"
    :status="project.status"
    :project-id="project.id"
    @action="handleStatusAction"
  />
</template>

<script setup>
import { ref } from 'vue'

const statusBadgeRef = ref(null)

const handleStatusAction = async ({ action, newStatus, projectId }) => {
  try {
    await api.projects.update(projectId, { status: newStatus })

    // Manually reset loading state
    statusBadgeRef.value?.resetLoading()
  } catch (error) {
    // Reset loading on error
    statusBadgeRef.value?.resetLoading()
  }
}
</script>
```

## Testing

### Component Tests

```javascript
import { mount } from '@vue/test-utils'
import { describe, it, expect, vi } from 'vitest'
import StatusBadge from '@/components/StatusBadge.vue'
import { vuetify } from '@/plugins/vuetify'

describe('StatusBadge', () => {
  it('renders status badge with correct color', () => {
    const wrapper = mount(StatusBadge, {
      global: { plugins: [vuetify] },
      props: {
        status: 'active',
        projectId: '123',
      },
    })

    expect(wrapper.find('.v-chip').classes()).toContain('bg-success')
    expect(wrapper.text()).toContain('Active')
  })

  it('shows confirmation dialog for destructive actions', async () => {
    const wrapper = mount(StatusBadge, {
      global: { plugins: [vuetify] },
      props: {
        status: 'active',
        projectId: '123',
      },
    })

    // Click badge to open menu
    await wrapper.find('.status-badge-chip').trigger('click')

    // Find and click "Delete" action
    const deleteAction = wrapper
      .findAll('.v-list-item')
      .find((item) => item.text().includes('Delete'))
    await deleteAction.trigger('click')

    // Confirm dialog should be visible
    expect(wrapper.find('.v-dialog').exists()).toBe(true)
    expect(wrapper.text()).toContain('Delete Project?')
  })
})
```

## Design Decisions

1. **Event-Driven Architecture**: Component emits events rather than making API
   calls directly, allowing parent components to handle business logic and
   maintain separation of concerns.

2. **Context-Aware Actions**: Menu items dynamically change based on current
   status, reducing cognitive load and preventing invalid state transitions.

3. **Progressive Disclosure**: Non-destructive actions execute immediately,
   while destructive actions require explicit confirmation, following
   established UX patterns.

4. **Loading States**: Visual feedback during async operations prevents
   double-submission and provides clear user feedback.

5. **Accessibility First**: Full keyboard navigation, ARIA labels, and semantic
   HTML ensure the component is usable by all users, including those with
   disabilities.

## Future Enhancements

- WebSocket integration for real-time status updates
- Undo/redo functionality for status changes
- Batch status updates for multiple projects
- Custom action definitions via props
- Status change history tracking
- Animation transitions between states

## License

Part of Giljo HQ - Internal component
