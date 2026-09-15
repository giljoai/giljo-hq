# AgentCardEnhanced Component Suite

Production-grade agent card components for Giljo HQ Handover 0077 dual-tab
interface.

## Components

### AgentCardEnhanced.vue

Reusable agent card that adapts to different modes (Launch Tab vs Jobs Tab) and
agent states.

**Location**: `frontend/src/components/projects/AgentCardEnhanced.vue`

**Props**:

```javascript
{
  agent: Object,           // Required - Agent job object
  mode: String,            // 'launch' | 'jobs' (default: 'jobs')
  instanceNumber: Number,  // Instance number for multi-instance (default: 1)
  isOrchestrator: Boolean, // Enable orchestrator features (default: false)
  showCloseoutButton: Boolean // Show closeout button (default: false)
}
```

**Emits**:

- `edit-mission(agent)` - Edit mission button clicked (Launch Tab)
- `launch-agent(agent)` - Launch agent button clicked (Jobs Tab, waiting state)
- `view-details(agent)` - Details button clicked (Jobs Tab, working state)
- `view-error(agent)` - View error button clicked (Jobs Tab, failed/blocked
  state)
- `closeout-project()` - Closeout project button clicked (Orchestrator, all
  complete)

**Usage Example**:

```vue
<template>
  <!-- Launch Tab Mode -->
  <AgentCardEnhanced
    :agent="agent"
    mode="launch"
    @edit-mission="handleEditMission"
  />

  <!-- Jobs Tab - Waiting State -->
  <AgentCardEnhanced
    :agent="agent"
    mode="jobs"
    @launch-agent="handleLaunchAgent"
  />

  <!-- Jobs Tab - Working State -->
  <AgentCardEnhanced
    :agent="workingAgent"
    mode="jobs"
    @view-details="handleViewDetails"
  />

  <!-- Jobs Tab - Complete State (Multi-instance) -->
  <AgentCardEnhanced :agent="completeAgent" mode="jobs" :instance-number="2" />

  <!-- Jobs Tab - Orchestrator with Closeout -->
  <AgentCardEnhanced
    :agent="orchestratorAgent"
    mode="jobs"
    is-orchestrator
    :show-closeout-button="allAgentsComplete"
    @closeout-project="handleCloseout"
  />
</template>

<script setup>
import AgentCardEnhanced from '@/components/projects/AgentCardEnhanced.vue'

const agent = {
  job_id: 'agent-123',
  agent_type: 'implementor',
  agent_name: 'Implementor Agent',
  status: 'waiting',
  mission: 'Implement authentication feature',
  progress: 0,
  current_task: null,
  messages: [],
  block_reason: null,
}

function handleEditMission(agent) {
  console.log('Edit mission for:', agent.job_id)
}

function handleLaunchAgent(agent) {
  console.log('Launch agent:', agent.job_id)
}

function handleViewDetails(agent) {
  console.log('View details:', agent.job_id)
}

function handleCloseout() {
  console.log('Closeout project')
}
</script>
```

### Agent Object Structure

```typescript
interface Agent {
  job_id: string // Unique job identifier
  agent_id?: string // Alternative identifier
  agent_type:
    | 'orchestrator'
    | 'analyzer'
    | 'implementor'
    | 'researcher'
    | 'reviewer'
    | 'tester'
  agent_name: string // Display name
  status: 'waiting' | 'working' | 'complete' | 'failed' | 'blocked'
  mission: string // Mission description
  progress?: number // 0-100 (working state only)
  current_task?: string // Current task description (working state only)
  messages?: Message[] // Array of messages
  block_reason?: string // Reason for failure/block
}

interface Message {
  id: number | string
  status: 'pending' | 'acknowledged'
  from: 'agent' | 'developer'
  content: string
}
```

## States and Behavior

### Launch Tab Mode (`mode="launch"`)

**Display**:

- Agent ID (truncated to 12 chars)
- Role/Mission (scrollable text area)
- No status badges
- No message badges

**Button**: "Edit Mission" **Emits**: `edit-mission`

---

### Jobs Tab - Waiting State (`status="waiting"`)

**Display**:

- Agent ID
- Status badge: "Waiting" (grey)
- Message badges (if messages exist)
- Truncated mission text

**Button**: "Launch Agent" (yellow) **Emits**: `launch-agent`

---

### Jobs Tab - Working State (`status="working"`)

**Display**:

- Agent ID
- Status badge: "Working" (blue)
- Message badges (if messages exist)
- Progress bar with percentage
- Current task text

**Button**: "Details" (outlined) **Emits**: `view-details`

---

### Jobs Tab - Complete State (`status="complete"`)

**Display**:

- Agent ID
- Status badge: "Complete" (yellow)
- Large "Complete" text (yellow, bold)
- Instance badge (if `instanceNumber > 1`)
- Grayed-out styling

**Button**: None (unless orchestrator with closeout)

---

### Jobs Tab - Silent State (`status="silent"`)

**Display**:

- Agent ID
- Status badge: "Silent" (amber/orange)
- Inactivity alert with last progress timestamp
- Message badges (if messages exist)
- Priority styling (moved to top)

**Button**: "Clear Silent" (amber) **Emits**: `clear-silent`

**Priority**: Cards with silent status are moved to the top of the list.

---

### Jobs Tab - Blocked State (`status="blocked"`)

**Display**:

- Agent ID
- Status badge: "Blocked" (orange)
- Warning alert with block reason
- Message badges (if messages exist)
- Priority styling (moved to top)

**Button**: "View Error" (warning color) **Emits**: `view-error`

**Priority**: Cards with blocked status are moved to the top of the list.

---

## Message Badges

Three separate chips displayed in Jobs Tab only:

1. **Unread (Red)**: Count of messages with `status === 'pending'`
2. **Acknowledged (Green)**: Count of messages with `status === 'acknowledged'`
3. **Sent (Grey)**: Count of messages with `from === 'developer'`

Message badges only appear when `mode === 'jobs'` and messages exist.

---

## Orchestrator Special Features

When `isOrchestrator={true}`:

1. **Launch Prompt Icons**: Displays `LaunchPromptIcons` component with Claude
   Code, Codex icons
2. **Closeout Button**: Shows green "Closeout Project" button when
   `showCloseoutButton={true}` (typically when all agents are complete)

---

## Styling and Design

### Card Dimensions

- **Width**: 280px (fixed)
- **Min Height**: 200px
- **Max Height**: 400px
- **Border**: `smooth-border` class (box-shadow inset, anti-aliased curves)
- **Border Radius**: 8px

### Header

- **Background**: Linear gradient (agent color → darkened by 10%)
- **Color**: White text
- **Padding**: 12px 16px
- **Font**: Bold, uppercase, letter-spacing

### Content Area

- **Scrollable**: Vertical scroll when content exceeds max height
- **Custom Scrollbar**: Styled for consistency
- **Padding**: 16px

### Hover Effects

- **Transform**: `translateY(-2px)`
- **Shadow**: Elevated shadow (0 4px 16px)
- **Transition**: 0.3s ease

### Priority States

- **Failed/Blocked**: Box shadow with orange glow (`rgba(255, 152, 0, 0.5)`)
- **Purpose**: Visual indicator for cards that need attention

---

## Dependencies

### Internal Components

- **ChatHeadBadge**: Circular badge with agent type abbreviation
- **LaunchPromptIcons**: AI coding tool icons with copy functionality

### External Libraries

- **Vue 3**: Composition API with `<script setup>`
- **Vuetify 3**: Material Design components (v-card, v-chip, v-btn,
  v-progress-linear, v-alert)

### Utilities

- **agentColors.js**: `getAgentColor()`, `darkenColor()`, `lightenColor()` (Luminous Pastels palette)
- **agent-colors.scss**: SCSS variables and mixins

---

## Accessibility (a11y)

### ARIA Attributes

- `role="article"` on card
- `aria-label` with agent type and status
- Meaningful button labels with icons

### Keyboard Navigation

- All buttons are keyboard accessible
- No negative tabindex values
- Enter/Space activate buttons

### Screen Reader Support

- Semantic HTML structure
- Descriptive ARIA labels
- Status changes announced

### Visual Accessibility

- High contrast support (when enabled)
- Color is not sole indicator of state
- Text labels accompany all visual indicators

---

## Testing

**Test File**: `frontend/tests/components/projects/AgentCardEnhanced.spec.js`

**Coverage**:

- ✅ Component rendering in all modes
- ✅ All agent states (waiting, working, complete, failed, blocked)
- ✅ Message badge calculations and display
- ✅ Event emissions for all actions
- ✅ Orchestrator special features
- ✅ Accessibility compliance
- ✅ Prop validation
- ✅ Edge cases and error handling

**Run Tests**:

```bash
cd frontend
npm run test -- AgentCardEnhanced
```

---

## Performance Considerations

### Optimization

- Fixed card dimensions prevent layout thrashing
- CSS transitions use `transform` (GPU-accelerated)
- Message count computations are memoized with `computed()`
- Conditional rendering reduces DOM nodes

### Best Practices

- Use `v-if` for content that changes modes
- Use `v-show` for content that toggles visibility
- Avoid deep nesting in templates
- Keep computed properties pure

---

## Common Patterns

### Display Agent Grid

```vue
<template>
  <div class="agent-grid">
    <AgentCardEnhanced
      v-for="agent in agents"
      :key="agent.job_id"
      :agent="agent"
      mode="jobs"
      @launch-agent="handleLaunch"
      @view-details="handleDetails"
      @view-error="handleError"
    />
  </div>
</template>

<style scoped>
.agent-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, 280px);
  gap: 16px;
  padding: 16px;
}
</style>
```

### Sort by Priority (Failed/Blocked First)

```javascript
const sortedAgents = computed(() => {
  return [...agents.value].sort((a, b) => {
    const aPriority = a.status === 'failed' || a.status === 'blocked' ? 0 : 1
    const bPriority = b.status === 'failed' || b.status === 'blocked' ? 0 : 1
    return aPriority - bPriority
  })
})
```

### Multi-Instance Agent Display

```vue
<template>
  <div v-for="(instance, index) in agentInstances" :key="instance.job_id">
    <AgentCardEnhanced
      :agent="instance"
      mode="jobs"
      :instance-number="index + 1"
    />
  </div>
</template>
```

---

## Related Documentation

- Internal design notes -
  Dual-tab interface specification
- [Agent Colors Config](../../config/agentColors.js) - Color system
  documentation
- [Agent Color Styles](../../styles/agent-colors.scss) - SCSS styling system

---

## Support Components

### ChatHeadBadge.vue

Square tinted badge component for agent identification (border-radius 8px, tinted background at 15% opacity).

**Props**:

- `agentType`: Agent type string
- `instanceNumber`: Instance number (default: 1)
- `size`: 'default' (32px) | 'compact' (24px)

**Display Logic**:

- Instance 1: Shows badge abbreviation (e.g., "Or", "Im", "An")
- Instance 2+: Shows first letter + number (e.g., "I2", "I3", "A2")

---

### LaunchPromptIcons.vue

AI coding tool icons with copy-to-clipboard functionality.

**Features**:

- Claude Code (orange)
- Codex CLI (purple)
- Click to copy MCP integration command
- Toast notification on successful copy

---

## Version History

- **v1.0.0** (2025-10-30): Initial production release for Handover 0077
  - Dual-mode support (Launch Tab / Jobs Tab)
  - Six agent states (waiting, working, complete, failed, blocked)
  - Message badge system (unread, acknowledged, sent)
  - Orchestrator special features
  - Comprehensive accessibility
  - Full test coverage
