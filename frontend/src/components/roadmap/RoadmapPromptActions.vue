<template>
  <div class="rm-copy-split">
    <v-btn
      color="primary"
      variant="flat"
      :prepend-icon="isEmpty ? 'mdi-playlist-plus' : 'mdi-refresh'"
      class="rm-copy-btn"
      :aria-label="isEmpty ? 'Copy a prompt to create the roadmap' : 'Copy a prompt to refresh the roadmap'"
      data-testid="roadmap-copy-prompt"
      @click="emitCopy()"
    >
      {{ isEmpty ? 'Create Roadmap' : 'Refresh Roadmap' }}
    </v-btn>
    <v-menu location="bottom end">
      <template #activator="{ props: menuProps }">
        <v-btn
          v-bind="menuProps"
          color="primary"
          variant="flat"
          icon="mdi-menu-down"
          class="rm-copy-caret"
          title="More prompt options"
          aria-label="More prompt options"
          data-testid="roadmap-prompt-menu"
        />
      </template>
      <v-list density="compact">
        <v-list-item
          prepend-icon="mdi-content-copy"
          title="Copy prompt"
          data-testid="roadmap-prompt-menu-copy"
          @click="emitCopy()"
        />
        <v-list-item
          prepend-icon="mdi-pencil"
          title="Edit prompt, then copy"
          data-testid="roadmap-prompt-menu-edit"
          @click="openEditor"
        />
      </v-list>
    </v-menu>

    <RoadmapPromptDialog
      v-model="dialogOpen"
      :prompt-text="promptText"
      @copy="emitCopy"
    />
  </div>
</template>

<script setup>
import { ref } from 'vue'
import RoadmapPromptDialog from './RoadmapPromptDialog.vue'

defineProps({
  isEmpty: { type: Boolean, default: false },
  promptText: { type: String, default: '' },
})

const emit = defineEmits(['copy'])

const dialogOpen = ref(false)

function openEditor() {
  dialogOpen.value = true
}

function emitCopy(editedText) {
  emit('copy', typeof editedText === 'string' ? editedText : undefined)
}

defineExpose({ dialogOpen, openEditor })
</script>

<style lang="scss" scoped>
.rm-copy-split {
  display: flex;
  align-items: stretch;
  gap: 1px;
}

.rm-copy-split .rm-copy-btn {
  border-top-right-radius: 0;
  border-bottom-right-radius: 0;
}

.rm-copy-split .rm-copy-caret {
  border-top-left-radius: 0;
  border-bottom-left-radius: 0;
}
</style>
