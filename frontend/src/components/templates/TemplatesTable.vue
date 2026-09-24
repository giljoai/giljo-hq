<template>
  <v-data-table
    :headers="headers"
    :items="templates"
    :search="search"
    :loading="loading"
    class="elevation-0 templates-table"
    item-key="id"
    :items-per-page="10"
    :sort-by="TEMPLATE_TABLE_DEFAULT_SORT"
    :item-class="(item) => (rowActive(item) ? '' : 'inactive-template')"
  >
    <template #item.name="{ item }">
      <div class="font-weight-medium">{{ item.name }}</div>
    </template>

    <template #item.product_id="{ item }">
      <v-chip
        size="x-small"
        variant="tonal"
        class="product-chip"
        :data-testid="`product-chip-${item.id}`"
      >
        {{ productNameFor(item) }}
      </v-chip>
    </template>

    <template #item.role="{ item }">
      <span
        class="template-role-badge"
        :style="{
          backgroundColor: hexToRgba(getCategoryColor(item.role), 0.15),
          color: getCategoryColor(item.role),
          opacity: rowActive(item) ? 1 : 0.4,
        }"
      >
        {{ item.role }}
      </span>
    </template>

    <template #item.updated_at="{ item }">
      <v-tooltip location="top" max-width="300" :disabled="!updatedState(item).exact">
        <template #activator="{ props }">
          <span
            v-bind="props"
            class="text-body-small"
            :class="{
              'text-muted-a11y': updatedState(item).kind === 'never-edited',
              'updated-new': updatedState(item).kind === 'added-today',
            }"
            :data-testid="`updated-state-${item.id}`"
          >
            {{ updatedState(item).label ?? formatDate(item.updated_at) }}
          </span>
        </template>
        <span v-if="updatedState(item).kind === 'added-today'">
          Added {{ formatDate(item.created_at) }}, and not edited since.
        </span>
        <span v-else-if="updatedState(item).kind === 'never-edited'">
          This agent has never been edited. Created {{ formatDate(item.created_at) }}.
        </span>
        <span v-else>Last edited: {{ formatDate(item.updated_at) }}</span>
      </v-tooltip>
    </template>

    <template #item.is_active="{ item }">
      <div class="d-flex align-center justify-center">
        <template v-if="item._system">
          <v-icon color="grey" size="small">mdi-lock</v-icon>
        </template>
        <template v-else-if="isForeignRow(item)">
          <v-tooltip location="top">
            <template #activator="{ props: tipProps }">
              <span
                v-bind="tipProps"
                class="foreign-row-dash"
                :data-testid="`foreign-agent-${item.id}`"
                >&mdash;</span
              >
            </template>
            <span>Switch this agent on from the {{ productNameFor(item) }} tab.</span>
          </v-tooltip>
        </template>
        <template v-else>
          <v-switch
            :model-value="rowActive(item)"
            :disabled="assignmentsLoading"
            color="primary"
            hide-details
            density="compact"
            :aria-label="
              rowActive(item) ? 'Disable agent for this product' : 'Enable agent for this product'
            "
            :data-testid="`template-toggle-${item.role}`"
            @update:model-value="$emit('toggle-active', item, $event)"
          />
          <v-tooltip v-if="remainingUserSlots === 0 && !rowActive(item)" location="top">
            <template #activator="{ props }">
              <v-icon v-bind="props" size="small" class="ml-1">
                mdi-help-circle-outline
              </v-icon>
            </template>
            <span>
              Maximum {{ userAgentLimit }} user-managed agents allowed (context budget limit).
              Deactivate another agent first.
            </span>
          </v-tooltip>
        </template>
      </div>
    </template>

    <template #item.actions="{ item }">
      <div v-if="item._system" class="d-flex align-center justify-end">
        <span
          v-if="canEditPrompt"
          class="orchestrator-prompt-link"
          data-testid="edit-orchestrator-prompt"
          @click="$emit('edit-orchestrator-prompt')"
        >
          Edit orchestrator prompt
          <v-icon size="14">mdi-arrow-right</v-icon>
        </span>
      </div>
      <div v-else-if="isForeignRow(item)" />
      <div v-else class="d-flex align-center justify-center">
        <v-menu>
          <template #activator="{ props }">
            <v-btn
              icon="mdi-dots-vertical"
              size="small"
              variant="text"
              class="icon-interactive"
              v-bind="props"
              aria-label="Template actions"
            ></v-btn>
          </template>

          <v-list density="compact" min-width="180">
            <v-list-item
              prepend-icon="mdi-pencil"
              title="Edit"
              @click="$emit('edit', item)"
            ></v-list-item>
            <v-list-item
              prepend-icon="mdi-content-copy"
              title="Duplicate"
              @click="$emit('duplicate', item)"
            ></v-list-item>
            <v-list-item
              v-if="item.can_reset"
              prepend-icon="mdi-refresh"
              title="Reset to Default"
              @click="$emit('reset', item)"
            ></v-list-item>
            <v-list-item
              prepend-icon="mdi-file-download-outline"
              title="Download profile (.md)"
              data-testid="action-download-profile"
              @click="$emit('download-profile', item)"
            ></v-list-item>
            <v-divider class="my-1" />
            <v-list-item
              prepend-icon="mdi-delete"
              title="Delete"
              @click="$emit('delete', item)"
            ></v-list-item>
          </v-list>
        </v-menu>
      </div>
    </template>

    <template #no-data>
      <div class="table-no-data" data-testid="templates-no-match">
        <div class="table-no-data__title">No agents match these filters</div>
        <v-btn size="small" variant="text" data-testid="clear-filters" @click="$emit('clear-filters')">
          Clear filters
        </v-btn>
      </div>
    </template>
  </v-data-table>
</template>

<script setup>
import { format } from 'date-fns'
import { getAgentColor as getAgentColorConfig } from '@/config/agentColors'
import { hexToRgba } from '@/utils/colorUtils'
import {
  templateUpdatedState,
  templateRowActive,
  TEMPLATE_TABLE_DEFAULT_SORT,
} from './templateTableConfig'

const props = defineProps({
  templates: {
    type: Array,
    default: () => [],
  },
  loading: {
    type: Boolean,
    default: false,
  },
  assignmentsLoading: {
    type: Boolean,
    default: false,
  },
  headers: {
    type: Array,
    default: () => [],
  },
  search: {
    type: String,
    default: '',
  },
  remainingUserSlots: {
    type: Number,
    default: 0,
  },
  userAgentLimit: {
    type: Number,
    default: 7,
  },
  showAllProducts: {
    type: Boolean,
    default: false,
  },
  viewedProductId: {
    type: String,
    default: null,
  },
  productNameFor: {
    type: Function,
    default: () => 'Unknown product',
  },
  canEditPrompt: {
    type: Boolean,
    default: true,
  },
})

const isForeignRow = (item) =>
  !item?._system && !!item?.product_id && item.product_id !== props.viewedProductId

defineEmits([
  'toggle-active',
  'edit',
  'duplicate',
  'reset',
  'delete',
  'download-profile',
  'clear-filters',
  'edit-orchestrator-prompt',
])


const getCategoryColor = (role) => getAgentColorConfig(role).hex

const formatDate = (date) => {
  if (!date) return 'N/A'
  return format(new Date(date), 'MMM dd, yyyy HH:mm')
}

const updatedState = (item) => templateUpdatedState(item)

const rowActive = (item) => templateRowActive(item)
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

/* FE-9385c: "Added today" is the one state the user should act on, so it is the
   one that carries brand accent. The other two states stay quiet — a screen
   where everything is highlighted highlights nothing. */
.updated-new {
  color: $color-brand-yellow;
  font-weight: 600;
}

.product-chip {
  font-weight: 600;
}

.foreign-row-dash {
  color: $color-text-muted;
  cursor: default;
}

.orchestrator-prompt-link {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  color: $color-brand-yellow;
  font-size: 0.78rem;
  font-weight: 500;
  cursor: pointer;
  white-space: nowrap;
}

.orchestrator-prompt-link:hover {
  text-decoration: underline;
}

.table-no-data {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 32px 16px;
  text-align: center;
}

.table-no-data__title {
  font-size: 0.9rem;
  color: $color-text-secondary;
}

.template-role-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: $border-radius-default;
  font-size: 0.75rem;
  font-weight: 600;
}

.templates-table {
  :deep(.v-data-table-footer) {
    background: var(--v-theme-surface);
    color: var(--v-theme-on-surface);
  }
}

:deep(.v-table) {
  background: transparent;
}

// Custom toggle colors: green when ON, faded blue when OFF
// Duplicated from container (scoped CSS stamps only the owner file's leaf nodes)
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

// Inactive template row styling
:deep(.inactive-template) {
  opacity: 0.5;

  td {
    color: var(--v-theme-on-surface);
  }
}
</style>
