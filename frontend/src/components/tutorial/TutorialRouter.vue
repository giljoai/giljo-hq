<template>
  <div class="router-screen">
    <div class="beat-eyebrow">06 · Your first product</div>
    <h2 class="beat-title">How do you want to start?</h2>
    <p class="beat-sub">Four doors, one destination: your product defined, activated, and ready for its first mission.</p>

    <div class="door-grid">
      <div
        class="door door--featured"
        data-testid="tutorial-door-D"
        role="button"
        tabindex="0"
        @click="$emit('pick', 'D')"
        @keydown.enter.prevent="$emit('pick', 'D')"
      >
        <v-icon size="23" class="door-icon">mdi-database-import-outline</v-icon>
        <span class="door-title">I have an existing codebase</span>
        <span class="door-desc">One prompt: your agent reads the repo, writes the vision doc, and fills the product card for you.</span>
        <span class="door-expect" data-testid="door-expect-existing">
          Needs an agent connected to {{ PRODUCT_NAME }}. It reads your whole repository, so
          expect it to run for a while — minutes, not seconds — before it reports back.
        </span>
        <span class="door-tag door-tag--featured">NO TYPING · TAKES A WHILE</span>
      </div>

      <div
        class="door"
        data-testid="tutorial-door-B"
        role="button"
        tabindex="0"
        @click="$emit('pick', 'B')"
        @keydown.enter.prevent="$emit('pick', 'B')"
      >
        <v-icon size="23" class="door-icon">mdi-chat-question-outline</v-icon>
        <span class="door-title">I have an idea — help me shape it</span>
        <span class="door-desc">A guided interview prompt for any chat tool. It asks the right questions and writes your vision document.</span>
        <span class="door-expect" data-testid="door-expect-idea">
          This one is a conversation between you and your own agent. {{ PRODUCT_NAME }} only
          hands you the opening prompt — it does not take part in the exchange or watch it.
          You come back here with the document it writes.
        </span>
        <span class="door-tag">~10 MINUTES · ANY CHAT TOOL</span>
      </div>

      <div
        class="door"
        data-testid="tutorial-door-A"
        role="button"
        tabindex="0"
        @click="$emit('pick', 'A')"
        @keydown.enter.prevent="$emit('pick', 'A')"
      >
        <v-icon size="23" class="door-icon">mdi-file-upload-outline</v-icon>
        <span class="door-title">I have a vision document</span>
        <span class="door-desc">Upload it. GiljoAI stages an analysis and your agent proposes the product setup.</span>
        <span class="door-expect" data-testid="door-expect-document">
          Upload the document, then copy the discovery prompt yourself and paste it into an
          agent connected to {{ PRODUCT_NAME }}. Nothing is copied for you.
        </span>
        <span class="door-tag">UPLOAD, THEN COPY THE PROMPT</span>
      </div>

      <div
        class="door"
        data-testid="tutorial-door-C"
        role="button"
        tabindex="0"
        @click="$emit('pick', 'C')"
        @keydown.enter.prevent="$emit('pick', 'C')"
      >
        <v-icon size="23" class="door-icon">mdi-pencil-outline</v-icon>
        <span class="door-title">I'll fill it in myself</span>
        <span class="door-desc">The classic form: info, setup, tech, architecture, testing. Full control.</span>
        <span class="door-expect" data-testid="door-expect-manual">
          No agent involved. This leaves the tour and opens the product form, where you type
          the details in yourself and activate when you are ready.
        </span>
        <span class="door-tag">MANUAL · LEAVES THE TOUR</span>
      </div>
    </div>
  </div>
</template>

<script setup>
// FE-9320: each door states what it actually expects of the user BEFORE they
// commit — whether it needs a connected agent, how long it runs, and who is
// actually doing the talking. Doors are addressed by NAME everywhere; the
// stored router_choice letters (D/B/A/C) do not match the displayed order and
// renaming them would need a migration for no user-visible benefit.
import { PRODUCT_NAME } from '@/branding'

defineEmits(['pick'])
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

.router-screen {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.beat-eyebrow {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.2em;
  color: $color-brand-yellow;
  text-transform: uppercase;
  margin-bottom: 10px;
}

.beat-title {
  margin: 0 0 6px;
  font-family: 'Outfit', $typography-font-primary;
  font-weight: 700;
  font-size: 28px;
  letter-spacing: -0.02em;
  color: $color-text-primary;
}

.beat-sub {
  margin: 0 0 18px;
  font-size: 14.5px;
  line-height: 1.55;
  color: var(--text-secondary);
}

.door-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

.door {
  background: $elevation-raised;
  border-radius: $border-radius-rounded;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.1);
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 7px;
  cursor: pointer;
  transition: transform 0.15s, box-shadow 0.15s;

  &:hover {
    transform: translateY(-2px);
    box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.2), 0 12px 32px rgba(0, 0, 0, 0.35);
  }

  &:focus-visible {
    outline: 2px solid rgba($color-brand-yellow, 0.55);
    outline-offset: 2px;
  }
}

.door--featured {
  box-shadow: inset 0 0 0 1px rgba($color-brand-yellow, 0.35);

  &:hover {
    box-shadow: inset 0 0 0 1px rgba($color-brand-yellow, 0.6), 0 12px 32px rgba(0, 0, 0, 0.35);
  }
}

.door-icon {
  color: $color-brand-yellow;
}

.door-title {
  font-family: 'Outfit', $typography-font-primary;
  font-weight: 600;
  font-size: 16px;
  color: $color-text-primary;
}

.door-desc {
  font-size: 12.5px;
  line-height: 1.5;
  color: var(--text-secondary);
}

/* What this door will ask of you — deliberately plainer and quieter than the
   pitch above it, but present before the click, not after. */
.door-expect {
  font-size: 11.5px;
  line-height: 1.5;
  color: var(--text-muted);
}

.door-tag {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 9.5px;
  color: var(--text-muted);
}

.door-tag--featured {
  color: $color-agent-researcher;
}
</style>
