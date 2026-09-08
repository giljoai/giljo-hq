<template>
  <div>
    <!-- HITL Closeout Toggle -->
    <div class="hitl-toggle-bar">
      <v-switch
        v-model="closeoutModeHitl"
        color="primary"
        density="compact"
        hide-details
        aria-label="Require user approval before project closeout"
        data-testid="closeout-mode-toggle"
        @update:model-value="toggleCloseoutMode"
      />
      <span class="hitl-toggle-label">Require approval before closeout</span>
      <v-tooltip location="bottom" max-width="340">
        <template #activator="{ props }">
          <v-icon v-bind="props" size="16" class="hitl-toggle-info">mdi-information-outline</v-icon>
        </template>
        When enabled, the orchestrator pauses for your review before closing a project — but only if there are deferred findings to review. Clean closeouts proceed automatically.
      </v-tooltip>
    </div>

    <!-- BE-9084 / BE-9542: Headless vs HITL launch toggle (account-wide, default Headless) -->
    <div class="hitl-toggle-bar">
      <v-switch
        v-model="allowHeadless"
        color="primary"
        density="compact"
        hide-details
        aria-label="Allow a headless CLI agent to self-advance from staging to implementation"
        data-testid="headless-launch-toggle"
        @update:model-value="toggleHeadless"
      />
      <span class="hitl-toggle-label">Allow headless CLI self-advance (skip the Implement click)</span>
      <v-tooltip location="bottom" max-width="360">
        <template #activator="{ props }">
          <v-icon v-bind="props" size="16" class="hitl-toggle-info">mdi-information-outline</v-icon>
        </template>
        This governs in-application, server-mediated launches only — the MCP launch_implementation tool that OAuth agent sessions use to advance a project from staging to building. On (the default) lets a trusted CLI/OAuth agent self-advance without a click. Turn it off to keep a human in the loop: the server will then refuse to authorize that launch until you press Implement yourself; only turn it off if you want every launch gated on your own click. It does not gate direct CLI interaction — an agent that reads a project and simply runs it locally never asks the server, so this toggle cannot reach it. Note: HITL guarantees the server will not authorize implementation early, but it cannot stop a non-compliant local orchestrator from inlining its own mission into an in-process subagent and working off the books (an accepted residual of local execution).
      </v-tooltip>
    </div>
  </div>
</template>

<script setup>
/**
 * OrchestrationToggles.vue — FE-9385c
 *
 * The two ACCOUNT-WIDE orchestration policy switches: HITL-vs-autonomous
 * closeout, and headless-vs-HITL launch (BE-9084). Extracted from
 * TemplateManager.vue, where they only ever lived because that tab had room —
 * neither has anything to do with the agent-template roster around them.
 *
 * Self-contained by design: it owns its own state, reads and writes its own
 * api.settings calls, and loads on its own mount. The parent passes nothing in
 * and gets nothing out, which is what makes it liftable to any settings surface.
 *
 * Both toggles update optimistically and revert on error.
 *
 * NOTE: the .v-switch thumb/track colour rules below came with the markup and
 * must stay with it. Scoped CSS does not cross a component boundary, so leaving
 * them in TemplateManager.vue would silently drop the green/blue switch styling
 * — the same boundary TemplatesTable.vue already documents for its row toggles.
 *
 * Edition scope: CE
 */
import { ref, onMounted } from 'vue'
import api from '@/services/api'
import { useToast } from '@/composables/useToast'

const { showToast } = useToast()

// HITL closeout mode
const closeoutModeHitl = ref(true)

// BE-9084 / BE-9542: account-wide Headless-vs-HITL launch toggle (default true =
// Headless, since BE-9542; the server is the source of truth, this is only the
// pre-load display value).
const allowHeadless = ref(true)

// HITL closeout mode toggle
async function toggleCloseoutMode(enabled) {
  const newMode = enabled ? 'hitl' : 'autonomous'
  const previousValue = closeoutModeHitl.value
  closeoutModeHitl.value = enabled
  try {
    // FE-9555: send the MERGED category, never just this one key. `PUT
    // /api/v1/settings/general` REPLACES the whole category
    // (update_settings("general", request.settings) -- no merge), so a partial
    // payload here destroyed every sibling key on each flip. Found live: saving
    // the execution-mode default and then flipping this toggle left the mode gone
    // from the database while both requests returned 200. The bug predates the
    // new setting; that setting is just the first sibling visible enough to
    // notice. Fixed here rather than by making the endpoint merge -- it is the
    // general-purpose "write the settings dict" verb and other callers may rely
    // on replacement (museum rule: do not change its observable behaviour).
    let general = {}
    try {
      const currentRes = await api.settings.getGeneral()
      general = currentRes.data?.settings || {}
    } catch (readErr) {
      // A failed read must not drop the change the user just made: write the one
      // key rather than abandoning it. Worst case is the pre-existing behaviour.
      console.warn('[OrchestrationToggles] could not read general settings to merge', readErr)
    }
    await api.settings.updateGeneral({ ...general, closeout_mode: newMode })
    showToast({
      message: enabled
        ? 'User approval required before project closeout'
        : 'Orchestrator will close projects autonomously',
      type: 'success',
    })
  } catch {
    closeoutModeHitl.value = previousValue
    showToast({ message: 'Failed to save closeout setting.', type: 'error' })
  }
}

async function loadCloseoutMode() {
  try {
    const generalRes = await api.settings.getGeneral()
    const generalSettings = generalRes.data?.settings || {}
    if (generalSettings.closeout_mode) {
      closeoutModeHitl.value = generalSettings.closeout_mode === 'hitl'
    }
  } catch {
    // Default stays true (hitl)
  }
}

// BE-9084: Headless-vs-HITL launch toggle (account-wide). Optimistic update with
// revert-on-error, mirroring the closeout toggle above.
async function toggleHeadless(enabled) {
  const previousValue = allowHeadless.value
  allowHeadless.value = enabled
  try {
    await api.settings.updateHeadlessLaunch(enabled)
    showToast({
      message: enabled
        ? 'Headless mode on — a trusted CLI agent may self-advance to implementation'
        : 'HITL mode — the human Implement step is enforced',
      type: 'success',
    })
  } catch {
    allowHeadless.value = previousValue
    showToast({ message: 'Failed to save headless setting.', type: 'error' })
  }
}

async function loadHeadlessLaunch() {
  try {
    const res = await api.settings.getHeadlessLaunch()
    allowHeadless.value = !!res.data?.allow_headless_launch
  } catch {
    // Default stays true (Headless), matching the server default (BE-9542)
  }
}

onMounted(() => {
  loadCloseoutMode()
  loadHeadlessLaunch()
})
</script>

<style scoped lang="scss">
/* HITL closeout toggle */
.hitl-toggle-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  /* FE-9555: 10px, not 4px. Measured in the browser: the v-switch thumb's own
     left edge sits 6px left of the track, so at 4px the OFF-state thumb rendered
     2px OUTSIDE this row's box and was visibly clipped, and the whole control sat
     6px left of the Execution mode select stacked above it. 10px puts the
     leftmost painted pixel -- the OFF thumb -- exactly on that select's left
     edge, so the group shares one left margin and nothing overflows. */
  padding-left: 10px;
}

.hitl-toggle-label {
  font-size: 0.875rem;
  color: var(--text-muted);
}

.hitl-toggle-info {
  color: var(--text-muted);
  cursor: help;
}

.hitl-toggle-bar :deep(.v-switch .v-selection-control) {
  min-height: auto;
}

// Custom toggle colors for these HITL v-switches: green when ON, faded blue when OFF
// Duplicated into TemplatesTable.vue for the row-level template toggles (scoped CSS boundary)
.v-switch {
  :deep(.v-switch__thumb) {
    background-color: rgba(33, 150, 243, 0.4); // Faded blue when OFF
  }

  :deep(.v-switch__track) {
    background-color: rgba(33, 150, 243, 0.2); // Faded blue track when OFF
  }
}

.v-switch :deep(.v-selection-control--dirty) {
  .v-switch__thumb {
    background-color: rgb(var(--v-theme-success));
  }

  .v-switch__track {
    background-color: rgba(76, 175, 80, 0.3); // Green track when ON
  }
}
</style>
