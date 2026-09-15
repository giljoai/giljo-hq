<template>
  <div class="agent-lab-trigger">
    <v-tooltip location="bottom">
      <template #activator="{ props: tooltipProps }">
        <v-btn
          v-bind="tooltipProps"
          icon
          size="small"
          variant="text"
          class="lab-btn"
          @click="showDialog = true"
        >
          <v-icon size="23">mdi-flask-outline</v-icon>
        </v-btn>
      </template>
      <span>Agent Lab</span>
    </v-tooltip>

    <v-dialog v-model="showDialog" max-width="680" scrollable>
      <v-card v-draggable class="lab-dialog-card smooth-border">
        <div class="dlg-header">
          <v-icon class="mr-2" size="22" color="primary">mdi-flask-outline</v-icon>
          <span class="dlg-title">Agent Lab</span>
          <v-spacer />
          <v-btn icon="mdi-close" variant="text" size="small" class="dlg-close" @click="showDialog = false" />
        </div>

        <v-divider />

        <v-card-text class="lab-content pa-4">
          <v-alert type="info" variant="tonal" density="compact" class="mb-4">
            <strong>Manual integration only.</strong> These are suggestions you copy-paste
            into your <strong>project description</strong> or agent missions. Nothing here
            is auto-applied.
          </v-alert>

          <v-expansion-panels variant="accordion" class="lab-panels">
            <v-expansion-panel>
              <v-expansion-panel-title>
                <v-icon size="18" class="mr-2">mdi-eye-outline</v-icon>
                Monitoring Agents
              </v-expansion-panel-title>
              <v-expansion-panel-text>
                <p class="mb-3">
                  By default, the orchestrator stages agents and exits. To have it actively
                  monitor agent status and interactions, add polling instructions to your
                  <strong>project description</strong>.
                </p>

                <div class="tip-box mb-3">
                  <div class="tip-label">Paste into project description:</div>
                  <code class="tip-code">After staging, monitor all agents by polling their status every 30 seconds using bash sleep. Check for status changes, new messages, and blocked agents. Report a summary after each poll cycle.</code>
                  <v-btn
                    size="x-small"
                    variant="text"
                    class="copy-btn"
                    @click="copyText('After staging, monitor all agents by polling their status every 30 seconds using bash sleep. Check for status changes, new messages, and blocked agents. Report a summary after each poll cycle.')"
                  >
                    <v-icon size="14">mdi-content-copy</v-icon>
                  </v-btn>
                </div>

                <v-alert type="warning" variant="tonal" density="compact" class="mb-2">
                  <strong>Token cost:</strong> Each poll cycle uses ~14K tokens (~12% of budget).
                  Use sparingly for long-running projects.
                </v-alert>

                <p class="text-body-small text-muted-a11y">
                  Works in both single-terminal (subagent) and multi-terminal mode.
                  All major CLI agents (Claude Code CLI, Codex, OpenCode) support bash sleep polling.
                </p>
              </v-expansion-panel-text>
            </v-expansion-panel>

            <v-expansion-panel>
              <v-expansion-panel-title>
                <v-icon size="18" class="mr-2">mdi-monitor-multiple</v-icon>
                Multi-Terminal Chains
              </v-expansion-panel-title>
              <v-expansion-panel-text>
                <p class="mb-3">
                  Chain multiple terminal sessions that execute sequentially, each spawning
                  the next upon completion. Useful for large projects with distinct phases.
                </p>

                <div class="tip-section mb-3">
                  <div class="tip-subtitle">How it works:</div>
                  <ol class="tip-list">
                    <li>Each terminal runs one handover with a colored tab for visual tracking</li>
                    <li>A chain log JSON file passes context between sessions</li>
                    <li>On completion, the agent spawns the next terminal automatically</li>
                  </ol>
                </div>

                <div class="tip-section mb-3">
                  <div class="tip-subtitle">Color scheme:</div>
                  <div class="color-chips">
                    <span class="color-chip" style="background: rgb(var(--v-theme-success));">DB</span>
                    <span class="color-chip" style="background: rgb(var(--v-theme-info));">Backend</span>
                    <span class="color-chip" style="background: rgb(var(--v-theme-error));">Frontend</span>
                    <span class="color-chip" style="background: var(--status-blocked);">Testing</span>
                    <span class="color-chip" style="background: rgb(var(--v-theme-error));">Final</span>
                  </div>
                </div>

                <div class="tool-selector mb-3">
                  <div class="tip-subtitle">AI coding agent:</div>
                  <v-chip-group v-model="selectedTool" mandatory selected-class="tool-chip-active">
                    <v-chip size="small" value="claude" variant="outlined">Claude Code CLI</v-chip>
                    <v-chip size="small" value="codex" variant="outlined">Codex</v-chip>
                  </v-chip-group>
                </div>

                <div v-if="selectedTool === 'claude'" class="tip-box mb-3">
                  <div class="tip-label">Spawn command (PowerShell):</div>
                  <code class="tip-code">powershell.exe -Command "Start-Process wt -ArgumentList '--title ""TITLE"" --tabColor ""#HEX"" -d ""WORKDIR"" cmd /k claude -p ""PROMPT"" --dangerously-skip-permissions' -Verb RunAs"</code>
                </div>

                <div v-if="selectedTool === 'codex'" class="tip-box mb-3">
                  <div class="tip-label">Spawn command (PowerShell):</div>
                  <code class="tip-code">powershell.exe -Command "Start-Process wt -ArgumentList '--title ""TITLE"" --tabColor ""#HEX"" -d ""WORKDIR"" cmd /k codex exec ""PROMPT"" --yolo' -Verb RunAs"</code>
                </div>

                <div class="tip-section mb-2">
                  <div class="tip-subtitle">Key tips:</div>
                  <ul class="tip-list">
                    <li>Keep launch prompts slim &mdash; point to the handover document</li>
                    <li>Include "Use Bash tool to RUN" to prevent agents from just printing commands</li>
                    <li>
                      Auto-approve flag:
                      <code v-if="selectedTool === 'claude'">--dangerously-skip-permissions</code>
                      <code v-else>--yolo</code>
                    </li>
                    <li>Store chain logs in <code>prompts/{project}_chain/chain_log.json</code></li>
                  </ul>
                </div>
              </v-expansion-panel-text>
            </v-expansion-panel>

            <v-expansion-panel>
              <v-expansion-panel-title>
                <v-icon size="18" class="mr-2">mdi-file-tree</v-icon>
                Chain Strategy Template
              </v-expansion-panel-title>
              <v-expansion-panel-text>
                <p class="mb-3">
                  For complex features, break work into sequenced phases with a shared
                  communication file. Download this template, customize it for your project,
                  and point your agents to it.
                </p>

                <div class="tip-section mb-3">
                  <div class="tip-subtitle">What the template covers:</div>
                  <ul class="tip-list">
                    <li>Pre-chain setup checklist</li>
                    <li>Chain log JSON schema with field descriptions</li>
                    <li>Orchestrator-gated workflow and dynamic sleep heuristics</li>
                    <li>Phase planning table and agent handover template</li>
                    <li>Orchestrator review checklist between phases</li>
                    <li>Common pitfalls and lessons learned</li>
                  </ul>
                </div>

                <v-btn
                  color="primary"
                  variant="tonal"
                  size="small"
                  prepend-icon="mdi-download"
                  class="mb-3"
                  @click="downloadTemplate"
                >
                  Download Template (.md)
                </v-btn>

                <p class="text-body-small text-muted-a11y mb-0">
                  Works with any MCP-compatible AI coding tool (Claude Code CLI, Codex CLI, OpenCode).
                </p>
              </v-expansion-panel-text>
            </v-expansion-panel>

          </v-expansion-panels>
        </v-card-text>
      </v-card>
    </v-dialog>

  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useClipboard } from '@/composables/useClipboard'
import { useToast } from '@/composables/useToast'

const { copy: clipboardCopy } = useClipboard()
const { showToast } = useToast()

const showDialog = ref(false)
const selectedTool = ref('claude')

async function copyText(text) {
  const success = await clipboardCopy(text)
  if (success) {
    showToast({ message: 'Copied to clipboard', type: 'success' })
  }
}

function downloadTemplate() {
  const link = document.createElement('a')
  link.href = '/templates/chain_strategy_template.md'
  link.download = 'chain_strategy_template.md'
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
}
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

.agent-lab-trigger {
  display: inline-flex;
  align-items: center;
}

.lab-btn {
  color: rgb(var(--v-theme-primary));
  transition: opacity $transition-normal ease;

  &:hover {
    opacity: 0.8;
  }
}

.lab-dialog-card {
  background: rgb(var(--v-theme-surface));
}

.lab-content {
  max-height: 70vh;
  overflow-y: auto;
}

.lab-panels {
  :deep(.v-expansion-panel-title) {
    font-size: 0.875rem;
    font-weight: 600;
    min-height: 44px;
    padding: 8px 16px;
  }

  :deep(.v-expansion-panel-text__wrapper) {
    padding: 12px 16px;
  }
}

.tool-selector {
  .tool-chip-active {
    background: rgba($color-brand-yellow, 0.15);
    border-color: rgb(var(--v-theme-primary));
    color: rgb(var(--v-theme-primary));
  }
}

.color-chips {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;

  .color-chip {
    padding: 3px 10px;
    border-radius: $border-radius-md;
    font-size: 0.7rem;
    font-weight: 600;
    color: white;
  }
}

</style>
