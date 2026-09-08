<template>
  <div class="step-complete">
    <!-- Header -->
    <div class="complete-header">
      <span class="complete-ring">
        <v-icon size="26" class="complete-icon">mdi-check</v-icon>
      </span>
      <h2 class="complete-title">You're all set!</h2>
      <p class="complete-subtitle">
        Your AI coding tools are connected and ready. Here's what to do next.
      </p>
    </div>

    <!-- Next-step cards — informational only. The user finishes via the
         footer's Finish/Done button, not by clicking a card. -->
    <div class="wiz-center">
      <div class="ctas" data-testid="launch-ctas">
        <div class="cta" data-testid="launch-cta-product">
          <span class="cta-icon cta-icon--yellow">
            <v-icon size="18">mdi-cube-outline</v-icon>
          </span>
          <div class="cta-text">
            <h4>Create your first product</h4>
            <p>Define what you're building.</p>
          </div>
        </div>
        <div class="cta" data-testid="launch-cta-dashboard">
          <span class="cta-icon cta-icon--sky">
            <v-icon size="18">mdi-view-dashboard-outline</v-icon>
          </span>
          <div class="cta-text">
            <h4>Open the dashboard</h4>
            <p>See products, projects &amp; jobs.</p>
          </div>
        </div>
        <div class="cta" data-testid="launch-cta-guide">
          <span class="cta-icon cta-icon--lavender">
            <v-icon size="18">mdi-book-open-page-variant-outline</v-icon>
          </span>
          <div class="cta-text">
            <h4>Read the guide</h4>
            <p>Learn how GiljoAI works.</p>
          </div>
        </div>
        <!-- FE-9503b: informational only, per ruling 19 -- no toggle, no
             preference stored, the dashboard cards above stay exactly as
             they were. Teaches that the harness door exists alongside them. -->
        <div class="cta" data-testid="launch-cta-terminal">
          <span class="cta-icon cta-icon--terminal">
            <v-icon size="18">mdi-console</v-icon>
          </span>
          <div class="cta-text">
            <h4>Drive from your terminal</h4>
            <p>Ask your connected agent to stage and run a project — no dashboard needed.</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
// Launch cards are informational only (Gradient Rail spec, FE-6259b) — the
// user finishes setup via the wizard footer's Finish/Done button, not by
// clicking a card. No props/emits needed.
</script>

<style lang="scss" scoped>
@use '../../styles/variables' as *;
@use '../../styles/design-tokens' as *;
@use '../../styles/setup-wizard-shared' as wiz;

@include wiz.setup-wiz-center;

.step-complete {
  max-width: 780px;
  margin: 0 auto;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

/* Header */
.complete-header {
  text-align: center;
  margin-bottom: 22px;
}

.complete-ring {
  display: inline-grid;
  place-items: center;
  width: 56px;
  height: 56px;
  border-radius: 50%;
  margin: 0 auto 12px;
  background: var(--gradient-brand);
  box-shadow: 0 0 0 6px rgba($gradient-brand-end, 0.12);
}

.complete-icon {
  color: $color-on-brand-ink;
}

.complete-title {
  font-family: 'Outfit', $typography-font-primary;
  font-size: 1.4rem;
  font-weight: 700;
  color: $color-text-primary;
  margin: 0 0 6px;
}

.complete-subtitle {
  font-size: 0.9rem;
  color: $lightest-blue;
  margin: 0;
  line-height: 1.5;
}

.ctas {
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 100%;
  max-width: 400px;
  margin: 0 auto;
}

.cta {
  display: flex;
  align-items: center;
  gap: 14px;
  text-align: left;
  border-radius: $border-radius-md;
  padding: 14px 16px;
  background: $elevation-elevated;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.1);
}

.cta-icon {
  width: 34px;
  height: 34px;
  border-radius: 9px;
  display: grid;
  place-items: center;
  flex: 0 0 34px;
}

.cta-icon--yellow {
  background: rgba($color-brand-yellow, 0.14);
  color: $color-brand-yellow;
}

.cta-icon--sky {
  background: rgba($color-agent-implementor, 0.14);
  color: $color-agent-implementor;
}

.cta-icon--lavender {
  background: rgba($color-agent-reviewer, 0.14);
  color: $color-agent-reviewer;
}

.cta-icon--terminal {
  background: rgba($color-agent-researcher, 0.14);
  color: $color-agent-researcher;
}

.cta-text h4 {
  font-family: 'Outfit', $typography-font-primary;
  font-weight: 600;
  font-size: 0.94rem;
  margin: 0 0 2px;
  color: $color-text-primary;
}

.cta-text p {
  margin: 0;
  font-size: 0.76rem;
  color: var(--text-muted);
}

</style>
