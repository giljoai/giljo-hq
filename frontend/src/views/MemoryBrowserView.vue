<template>
  <v-container data-test="memory-browser">
    <!-- Header (harmonized with ProjectsView / TasksView / RoadmapView) -->
    <v-row class="align-center mb-4 main-window-reveal main-window-reveal--hero main-window-delay-1">
      <v-col>
        <h1 class="text-headline-large">360 Memory</h1>
        <p class="text-body-medium text-muted-a11y mt-1">
          Your product's cumulative project history — every closeout, decision, and discovery your
          agents recorded. Search across summaries, outcomes, and decisions, filter by tag or
          project, and expand any entry to read its full write-up.
        </p>
      </v-col>
    </v-row>

    <!-- No Active Product -->
    <v-alert
      v-if="!productId"
      type="info"
      variant="tonal"
      class="ma-4 main-window-reveal main-window-delay-2"
      data-test="memory-no-product"
    >
      No product is open. Add a product to browse its 360 Memory.
    </v-alert>

    <template v-else>
      <!-- Toolbar: search + filters + sort + group toggle -->
      <div class="filter-bar main-window-reveal main-window-delay-2">
        <v-text-field
          v-model="searchText"
          placeholder="Search summaries, outcomes, decisions…"
          prepend-inner-icon="mdi-magnify"
          density="compact"
          variant="solo"
          flat
          hide-details
          clearable
          class="mem-search"
          data-test="memory-search"
        />
        <v-select
          v-model="selectedTags"
          :items="availableTags"
          placeholder="Tags"
          multiple
          chips
          closable-chips
          density="compact"
          variant="solo"
          flat
          hide-details
          clearable
          class="mem-filter"
          data-test="memory-tag-filter"
        />
        <v-select
          v-model="selectedProjectId"
          :items="projectFilterItems"
          item-title="name"
          item-value="id"
          placeholder="Project"
          density="compact"
          variant="solo"
          flat
          hide-details
          clearable
          class="mem-filter"
          data-test="memory-project-filter"
        />
        <v-select
          v-model="sortMode"
          :items="sortOptions"
          placeholder="Sort"
          density="compact"
          variant="solo"
          flat
          hide-details
          class="mem-sort"
          data-test="memory-sort"
        />
        <!-- Group toggle: a real button matching the Projects filter-bar buttons
             (outlined when off, flat-primary when on) instead of a custom pill. -->
        <v-btn
          :variant="groupByProject ? 'flat' : 'outlined'"
          :color="groupByProject ? 'primary' : undefined"
          prepend-icon="mdi-folder-multiple-outline"
          class="mem-group-toggle"
          role="switch"
          :aria-checked="groupByProject"
          data-test="memory-group-toggle"
          @click="groupByProject = !groupByProject"
        >
          Group by project
        </v-btn>
      </div>

      <!-- Loading -->
      <div v-if="loading" class="mem-loading" data-test="memory-loading">
        <v-progress-circular indeterminate size="28" width="3" color="primary" />
        <span class="ml-3 text-body-medium text-muted-a11y">Loading memory entries…</span>
      </div>

      <!-- Empty -->
      <v-alert
        v-else-if="filteredEntries.length === 0"
        type="info"
        variant="tonal"
        density="compact"
        class="mt-4"
        data-test="memory-empty"
      >
        {{ entries.length === 0
          ? 'No 360 Memory entries yet for this product. They appear as your agents close out projects.'
          : 'No entries match your search and filters.' }}
      </v-alert>

      <!-- Surface-card list panel (grouped + flat), harmonized with the
           Projects / Tasks list surfaces. -->
      <v-card
        v-else
        class="memory-table-card smooth-border main-window-reveal main-window-delay-3"
        data-test="memory-list-card"
      >
        <!-- Grouped by project -->
        <template v-if="groupByProject">
          <section
            v-for="group in groupedByProjectEntries"
            :key="group.project_id || '__none__'"
            class="mem-group"
            data-test="memory-group"
          >
            <h2 class="mem-group-title">
              <v-icon size="16" class="mr-1">mdi-folder-outline</v-icon>
              <span class="mem-group-name">{{ group.project_name }}</span>
              <span class="mem-group-count">{{ group.entries.length }}</span>
            </h2>
            <MemoryEntryRow
              v-for="entry in group.entries"
              :key="entry.id"
              :entry="entry"
              :expanded="expandedId === entry.id"
              :rendered-summary="renderedSummary(entry)"
              @toggle="toggleExpand(entry.id)"
            />
          </section>
        </template>

        <!-- Flat sortable list -->
        <template v-else>
          <MemoryEntryRow
            v-for="entry in filteredEntries"
            :key="entry.id"
            :entry="entry"
            :expanded="expandedId === entry.id"
            :rendered-summary="renderedSummary(entry)"
            @toggle="toggleExpand(entry.id)"
          />
        </template>
      </v-card>
    </template>
  </v-container>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useMemoryStore } from '@/stores/memoryStore'
import { useProductStore } from '@/stores/products'
import { useSanitizeMarkdown } from '@/composables/useSanitizeMarkdown'
import MemoryEntryRow from '@/components/memory/MemoryEntryRow.vue'

const memoryStore = useMemoryStore()
const productStore = useProductStore()
const { sanitizeMarkdown } = useSanitizeMarkdown()

const {
  entries,
  filteredEntries,
  groupedByProjectEntries,
  availableTags,
  availableProjects,
  loading,
  searchText,
  selectedTags,
  selectedProjectId,
  sortMode,
  groupByProject,
} = storeToRefs(memoryStore)

const productId = computed(() => productStore.effectiveProductId)

// "All projects" sentinel + the discovered projects for the project filter.
const projectFilterItems = computed(() => availableProjects.value)

const sortOptions = [
  { title: 'Newest first', value: 'date_desc' },
  { title: 'Oldest first', value: 'date_asc' },
  { title: 'Sequence (high→low)', value: 'sequence_desc' },
  { title: 'Sequence (low→high)', value: 'sequence_asc' },
]

// Inline expand-on-click state (one open at a time).
const expandedId = ref(null)
function toggleExpand(id) {
  expandedId.value = expandedId.value === id ? null : id
}

// Markdown is rendered in the VIEW (v-html-safe via useSanitizeMarkdown:
// marked + hardened DOMPurify), never in the store.
function renderedSummary(entry) {
  return sanitizeMarkdown(entry.summary || '_No summary recorded._')
}

async function load() {
  if (productId.value) {
    await memoryStore.fetchMemoryEntries(productId.value)
  }
}

onMounted(load)
// Reload when the active product changes.
watch(productId, (id, prev) => {
  if (id && id !== prev) load()
})

// BE-6082: graceful server-side search. Debounce keystrokes, then hit the
// server ?search= path (empty term falls back to a client-side full reload).
let searchDebounce
watch(searchText, (term) => {
  clearTimeout(searchDebounce)
  searchDebounce = setTimeout(() => {
    if (productId.value) memoryStore.searchMemoryEntries(productId.value, term)
  }, 250)
})
</script>

<style scoped lang="scss">
@use '../styles/design-tokens' as *;

.filter-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 16px;
}

// Search + filters: match the Projects filter bar — solo+flat field with an
// inset smooth-border (not Vuetify's outline) and a brand-yellow focus ring.
.mem-search {
  flex: 1 1 280px;
  min-width: 220px;
}

.mem-filter {
  flex: 0 1 200px;
  min-width: 160px;
}

.mem-sort {
  flex: 0 1 180px;
  min-width: 150px;
}

.mem-search,
.mem-filter,
.mem-sort {
  :deep(.v-field) {
    box-shadow: inset 0 0 0 1px var(--smooth-border-color, rgba(255, 255, 255, 0.10));
    border-radius: $border-radius-default;
  }
  :deep(.v-field:focus-within) {
    box-shadow: inset 0 0 0 1px rgba($color-brand-yellow, 0.3);
  }
}

.mem-group-toggle {
  flex: 0 0 auto;
}

.mem-loading {
  display: flex;
  align-items: center;
  padding: 32px 0;
}

// Smooth-border surface panel, matching the Projects / Tasks list cards. The
// raised surface fill (NOT transparent) is what makes it read as the same panel
// as the Projects table — $elevation-raised == the Vuetify card surface.
.memory-table-card {
  border: none !important;
  border-radius: $border-radius-rounded !important;
  overflow: hidden;
  background: $elevation-raised;
  padding: 6px 0;
}

.mem-group {
  margin-bottom: 16px;

  &:last-child {
    margin-bottom: 0;
  }
}

// Tokenized section header: app default font, secondary label color, tinted
// count pushed to the trailing edge.
.mem-group-title {
  display: flex;
  align-items: center;
  font-size: 0.78rem;
  font-weight: 600;
  color: $color-text-secondary;
  padding: 10px 14px 8px;
  border-bottom: 1px solid $color-border-tertiary;
}

.mem-group-name {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mem-group-count {
  flex-shrink: 0;
  margin-left: 8px;
  font-size: 0.65rem;
  font-family: 'IBM Plex Mono', monospace;
  color: var(--text-muted);
  background: rgba($color-surface, 0.06);
  border-radius: $border-radius-pill;
  padding: 1px 8px;
}
</style>
