<template>
  <v-menu
    :model-value="open"
    :close-on-content-click="false"
    location="right"
    offset="8"
    @update:model-value="$emit('menu-toggle', $event)"
  >
    <template #activator="{ props: logMenuProps }">
      <v-tooltip location="right">
        <template #activator="{ props: tipProps }">
          <div
            v-bind="{ ...logMenuProps, ...tipProps }"
            class="nav-orb nav-orb--logs"
            role="button"
            tabindex="0"
            aria-label="Download server logs"
          >
            <v-icon icon="mdi-file-document-outline" size="18" />
          </div>
        </template>
        Server logs
      </v-tooltip>
    </template>

    <v-card class="smooth-border log-download-menu" min-width="240">
      <v-list density="compact">
        <v-list-item
          prepend-icon="mdi-download"
          title="Download Current Log"
          @click="$emit('download-current')"
        />

        <v-divider class="my-1" />

        <v-list-subheader class="log-menu-subheader">Archives</v-list-subheader>

        <template v-if="logArchivesLoading">
          <v-list-item>
            <v-progress-linear indeterminate color="primary" class="my-2" />
          </v-list-item>
        </template>

        <template v-else-if="logArchives.length === 0">
          <v-list-item disabled title="No archives available" />
        </template>

        <template v-else>
          <v-list-item
            v-for="archive in logArchives"
            :key="archive.filename"
            @click="$emit('download-archive', archive.filename)"
          >
            <v-list-item-title>{{ archiveTitle(archive) }}</v-list-item-title>
            <v-list-item-subtitle class="log-archive-size"
              >{{ archive.size_kb }} KB</v-list-item-subtitle
            >
            <template #prepend>
              <v-icon size="18">mdi-file-clock-outline</v-icon>
            </template>
          </v-list-item>
        </template>
      </v-list>
    </v-card>
  </v-menu>
</template>

<script setup>
defineProps({
  open: {
    type: Boolean,
    default: false,
  },
  logArchives: {
    type: Array,
    default: () => [],
  },
  logArchivesLoading: {
    type: Boolean,
    default: false,
  },
})

defineEmits(['menu-toggle', 'download-current', 'download-archive'])

function formatArchiveDate(dateStr) {
  if (!dateStr) return 'Unknown'
  const date = new Date(`${dateStr}T00:00:00`)
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

// Size-rotated archives can share a date, so the date alone does not identify
// them. Legacy date-named archives have no index and need no suffix.
function archiveTitle(archive) {
  const when = formatArchiveDate(archive.date)
  return archive.rotation_index ? `${when} (#${archive.rotation_index})` : when
}
</script>

<style scoped lang="scss">
/* ─── ORBS: unified round icons (duplicated from parent — scoped styles don't cross) ─── */
.nav-orb {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.2s ease;
}

.nav-orb:hover {
  transform: scale(1.08);
}

.nav-orb:active {
  transform: scale(0.95);
}

// Logs: muted color, same orb style
.nav-orb--logs {
  background: rgba(136, 149, 168, 0.15);
  color: var(--text-muted);

  &:hover {
    background: rgba(136, 149, 168, 0.25);
  }
}

// ─── LOG DOWNLOAD MENU ───
.log-download-menu {
  max-height: 320px;
  overflow-y: auto;
}

.log-menu-subheader {
  color: var(--text-muted);
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.log-archive-size {
  color: var(--text-muted);
  font-size: 0.75rem;
}

// Mobile: bigger touch targets
@media (max-width: 1024px) {
  .nav-orb {
    width: 44px;
    height: 44px;
  }
}
</style>
