<template>
  <div class="agent-link" data-testid="connect-agent-link">
    <span class="agent-link-text">Prefer to let your agent do it? Give it this link</span>
    <code class="agent-link-url" data-testid="connect-agent-link-url">{{ connectUrl }}</code>
    <button
      type="button"
      class="agent-link-copy"
      data-testid="connect-agent-link-copy"
      aria-label="Copy the connect link"
      @click="copyLink"
    >
      <v-icon size="14">mdi-content-copy</v-icon>
    </button>
  </div>
</template>

<script setup>
import { getApiBaseUrl } from '@/composables/useApiUrl'
import { useClipboard } from '@/composables/useClipboard'
import { useToast } from '@/composables/useToast'

const { copy: clipboardCopy } = useClipboard()
const { showToast } = useToast()

const connectUrl = `${getApiBaseUrl() || window.location.origin}/connect.md`

async function copyLink() {
  const success = await clipboardCopy(connectUrl)
  showToast(
    success
      ? { message: 'Copied to clipboard', type: 'success' }
      : { message: 'Copy failed. Select the text and press Ctrl+C', type: 'warning' },
  )
}
</script>

<style scoped lang="scss">
@use '../../styles/variables' as *;
@use '../../styles/design-tokens' as *;

.agent-link {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 16px;
  font-size: 0.8rem;
  color: $color-text-secondary;
}

.agent-link-url {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.75rem;
  color: $color-text-primary;
}

.agent-link-copy {
  display: inline-flex;
  align-items: center;
  background: transparent;
  border: 0;
  padding: 4px;
  cursor: pointer;
  color: inherit;
}
</style>
