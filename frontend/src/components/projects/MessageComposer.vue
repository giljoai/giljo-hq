<template>
  <div class="message-composer smooth-border">
    <div class="composer-channels">
      <v-btn
        class="recipient-btn smooth-border"
        :variant="selectedRecipient === 'orchestrator' ? 'flat' : 'outlined'"
        color="yellow-darken-2"
        @click="selectedRecipient = 'orchestrator'"
      >
        Orchestrator
      </v-btn>

      <v-btn
        class="broadcast-btn smooth-border"
        :variant="selectedRecipient === 'broadcast' ? 'flat' : 'outlined'"
        color="yellow-darken-2"
        @click="selectedRecipient = 'broadcast'"
      >
        Broadcast
      </v-btn>
    </div>

    <div class="composer-input">
      <v-text-field
        v-model="messageText"
        class="message-input"
        placeholder="Type message..."
        variant="outlined"
        density="compact"
        hide-details
        aria-label="Message to agent"
        @keyup.enter="sendMessage"
      />

      <v-btn
        icon="mdi-play"
        class="send-btn"
        color="yellow-darken-2"
        :loading="sending"
        :disabled="!messageText.trim()"
        aria-label="Send message"
        @click="sendMessage"
      />
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useCommHubStore } from '@/stores/commHubStore'
import { useProjectBoundThread } from '@/composables/useProjectBoundThread'
import { useToast } from '@/composables/useToast'

/**
 * MessageComposer — standalone message input panel extracted from JobsTab.
 * Sends direct or broadcast messages to agents in a project.
 *
 * BE-9012d Part 1: rewired off the retired agent bus (`/api/v1/messages/*`,
 * `MessageRoutingService`) onto the Hub's thread primitives (`commHubStore` ->
 * `/api/v1/threads/*`) — the same store HubComposer.vue posts through.
 * "Orchestrator" posts a DIRECTED, requires_action message (mirrors the old
 * bus send_message wake/reactivation); "Broadcast" posts with no
 * to_participant (mirrors HubComposer's own broadcast — a project-anchored
 * thread auto-enrolls the project's roster server-side). Both target the
 * project's canonical bound Hub thread, resolved with the SAME precedence
 * CommThreadService.resolve_or_create_bound_thread uses server-side (ce_0072
 * D8 migration + D9 shims): exactly one live project-bound thread -> use it;
 * none -> create one with the reserved marker subject; several -> the
 * marker-subject one if present, else the oldest. Composed from the existing
 * threads.list/threads.create calls — no new endpoint.
 */

const props = defineProps({
  projectId: {
    type: String,
    required: true,
  },
  // FE-6174b: chain implementation reroute. When chainMode is true and the
  // project-less conductor is addressable (conductorAgentId + chainRunId),
  // the "Orchestrator" button targets the chain CONDUCTOR on its own chain
  // coordination thread instead of the active project's own orchestrator.
  // "Broadcast" always stays scoped to the active project's bound thread (the
  // Hub has no all-projects broadcast primitive — see FE-6131d).
  chainMode: {
    type: Boolean,
    default: false,
  },
  conductorAgentId: {
    type: String,
    default: '',
  },
  // BE-9012d Part 1: the run_id used to resolve the conductor's OWN "Chain run
  // {run_id} coordination hub" Hub thread via commHub.searchThreads(runId) —
  // the same lookup the conductor/sub-orchestrators use themselves. The
  // conductor is project-less (BE-6184), so it has no project-bound thread to
  // address directly; replaces the dead conductorProjectId (always empty
  // under the project-less conductor design — BE-9012d field finding).
  chainRunId: {
    type: String,
    default: '',
  },
  // BE-9012d Part 1: the active project's own orchestrator agent_id, needed
  // to address a DIRECTED Hub post (the old bus resolved 'orchestrator' by
  // role; the Hub addresses participants by agent_id).
  orchestratorAgentId: {
    type: String,
    default: '',
  },
})

const emit = defineEmits(['message-sent'])

const commHub = useCommHubStore()
const { resolveProjectThread: resolveProjectBoundThread } = useProjectBoundThread()
const { showToast } = useToast()

const messageText = ref('')
const selectedRecipient = ref('orchestrator')
const sending = ref(false)

// True when the chain conductor is addressable (a sequence run with a
// registered, project-less conductor + a resolvable run_id). Until then the
// Orchestrator reroute falls back to the local project path.
const conductorReady = () =>
  props.chainMode && Boolean(props.conductorAgentId) && Boolean(props.chainRunId)

/** Resolve THE project's bound Hub thread — shared with useChainLifecycle
 *  (see useProjectBoundThread for the precedence this mirrors). */
async function resolveProjectThread() {
  return resolveProjectBoundThread(props.projectId)
}

/**
 * Resolve the chain conductor's own coordination thread. The conductor mints
 * this itself as the FIRST action of its protocol (subject "Chain run
 * {run_id} coordination hub", never surfaced on the run record), so the FE
 * finds it the SAME way every sub-orchestrator does: list_threads(query=run_id).
 * Returns null if the conductor hasn't created it yet — never fabricated.
 */
async function resolveConductorThread() {
  const results = await commHub.searchThreads(props.chainRunId)
  const subject = `Chain run ${props.chainRunId} coordination hub`
  return results.find((t) => t.subject === subject) || results[0] || null
}

async function sendMessage() {
  if (!messageText.value.trim()) {
    showToast({ message: 'Message cannot be empty', type: 'warning', timeout: 3000 })
    return
  }

  sending.value = true
  const content = messageText.value.trim()

  try {
    if (selectedRecipient.value === 'orchestrator' && conductorReady()) {
      // Reroute the directive to the conductor (its own agent_id) on the
      // chain's coordination thread. requires_action=true mirrors the old bus
      // send_message wake — delivery stays poll-based either way.
      const thread = await resolveConductorThread()
      if (!thread) {
        showToast({
          message: "The conductor hasn't set up its coordination thread yet — try again shortly.",
          type: 'warning',
          timeout: 5000,
        })
        return
      }
      await commHub.postMessage(thread.thread_id, {
        content,
        to_participant: props.conductorAgentId,
        requires_action: true,
      })
    } else {
      const thread = await resolveProjectThread()
      const body = { content, requires_action: false }
      if (selectedRecipient.value === 'orchestrator') {
        if (!props.orchestratorAgentId) {
          showToast({ message: 'No orchestrator found for this project.', type: 'error', timeout: 5000 })
          return
        }
        body.to_participant = props.orchestratorAgentId
        body.requires_action = true
      }
      await commHub.postMessage(thread.thread_id, body)
    }

    showToast({ message: 'Message sent successfully', type: 'success', timeout: 3000 })
    messageText.value = ''
    emit('message-sent')
  } catch (error) {
    console.error('[MessageComposer] Send message failed:', error)
    const msg = error.response?.data?.detail || error.message || 'Failed to send message'
    showToast({ message: `Failed to send message: ${msg}`, type: 'error', timeout: 5000 })
  } finally {
    sending.value = false
  }
}
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

.message-composer {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 18px;
  background: $elevation-raised;
  border-radius: $border-radius-rounded;
  margin-bottom: 20px;

  .composer-channels {
    display: flex;
    gap: 4px;
    flex-shrink: 0;
    order: 0;
  }

  .composer-input {
    display: flex;
    flex: 1;
    gap: 8px;
    align-items: center;
    min-width: 0;
    order: 1;
  }

  @media (max-width: 576px) {
    flex-wrap: wrap;

    .composer-channels {
      order: 2;
      width: 100%;
    }

    .composer-input {
      order: 1;
      width: 100%;
      flex-basis: 100%;
    }
  }

  .recipient-btn,
  .broadcast-btn {
    border: none !important;
    border-radius: $border-radius-pill;
    text-transform: none;
    font-size: 0.72rem;
    font-weight: 500;
    padding: 6px 14px;
    color: $color-text-muted;
    transition: all $transition-normal ease;

    &.v-btn--variant-flat {
      background: rgba(255, 195, 0, 0.12);
      color: $color-brand-yellow;
      box-shadow: none;
    }

    &.v-btn--variant-outlined {
      background: transparent;

      &:hover {
        background: rgba(255, 255, 255, 0.04);
        color: $color-text-secondary;
      }
    }
  }

  .message-input {
    flex: 1;

    ::v-deep(.v-field) {
      background: $elevation-elevated;
      border: none !important;
      box-shadow: inset 0 0 0 1px var(--smooth-border-color, rgba(255, 255, 255, 0.10));
      border-radius: $border-radius-default;

      input {
        color: $color-text-primary;
        font-size: 0.78rem;
        padding: 8px 12px;

        &::placeholder {
          color: $color-text-muted;
        }
      }

      &:hover {
        box-shadow: inset 0 0 0 1px var(--smooth-border-color, rgba(255, 255, 255, 0.14));
      }

      &.v-field--focused {
        box-shadow: inset 0 0 0 1px rgba($color-brand-yellow, 0.3);
      }
    }
  }

  .send-btn {
    min-width: auto;
    width: 36px;
    height: 36px;
    border-radius: $border-radius-default;

    &:disabled {
      opacity: 0.4;
    }
  }
}
</style>
