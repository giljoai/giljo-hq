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
    :item-class="(item) => (item.is_active ? '' : 'inactive-template')"
  >
    <template #item.name="{ item }">
      <div class="font-weight-medium">{{ item.name }}</div>
    </template>

    <template #item.role="{ item }">
      <span
        class="template-role-badge"
        :style="{
          backgroundColor: hexToRgba(getCategoryColor(item.role), 0.15),
          color: getCategoryColor(item.role),
          opacity: item.is_active ? 1 : 0.4,
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

    <template #item.export_status="{ item }">
      <div class="d-flex flex-column align-center">
        <template v-if="item._system">
          <span class="text-body-small text-muted-a11y">System managed</span>
        </template>
        <template v-else-if="item.user_managed_export">
          <v-chip size="small" color="info" variant="tonal" prepend-icon="mdi-account-check">
            User Managed
          </v-chip>
        </template>
        <template v-else>
          <v-chip
            v-if="item.may_be_stale && item.is_active"
            size="small"
            color="warning"
            prepend-icon="mdi-alert"
            class="mb-1"
            aria-label="Template may be outdated"
          >
            May be outdated
          </v-chip>
          <v-tooltip location="top" max-width="300">
            <template #activator="{ props }">
              <span
                v-bind="props"
                class="text-body-small text-muted-a11y"
                :class="{ 'text-warning': item.may_be_stale }"
              >
                {{ item.last_exported_at ? formatDate(item.last_exported_at) : 'Never exported' }}
              </span>
            </template>
            <span v-if="item.may_be_stale">
              This template was modified after the last export. Run the giljo_setup tool ("Agents only") in your CLI tool to update.
            </span>
            <span v-else-if="item.last_exported_at">
              Last exported: {{ formatDate(item.last_exported_at) }}
            </span>
            <span v-else>
              This template has never been exported. Run the giljo_setup tool ("Agents only") in your CLI tool to install it.
            </span>
          </v-tooltip>
        </template>
      </div>
    </template>

    <template #item.is_active="{ item }">
      <div class="d-flex align-center justify-center">
        <template v-if="item._system">
          <v-icon color="grey" size="small">mdi-lock</v-icon>
        </template>
        <template v-else>
          <!-- BE-9385a: this switch is the PER-PRODUCT enable, written to the
               product_agent_assignments junction. ``product_active`` is undefined
               until the parent has loaded the active product's assignments, and
               until then it falls back to the tenant flag -- the same tolerance
               the server applies to a product with no junction rows. The
               tenant-wide switch is a SEPARATE control -- the edit dialog's
               "Available in all products" (BE-9394); this one never writes it. -->
          <v-switch
            :model-value="item.product_active ?? item.is_active"
            :disabled="!item.is_active"
            color="primary"
            hide-details
            density="compact"
            :aria-label="
              (item.product_active ?? item.is_active)
                ? 'Disable agent for this product'
                : 'Enable agent for this product'
            "
            :data-testid="`template-toggle-${item.role}`"
            @update:model-value="$emit('toggle-active', item, $event)"
          />
          <v-tooltip v-if="!item.is_active" location="top">
            <template #activator="{ props }">
              <v-icon v-bind="props" size="small" class="ml-1">
                mdi-help-circle-outline
              </v-icon>
            </template>
            <span v-if="remainingUserSlots === 0">
              Maximum {{ userAgentLimit }} user-managed agents allowed (context budget limit).
              Deactivate another agent first.
            </span>
            <span v-else>
              This agent is switched off for your whole account, so it cannot be enabled for
              a single product. Turn on &ldquo;Available in all products&rdquo; under Edit first.
            </span>
          </v-tooltip>
        </template>
      </div>
    </template>

    <template #item.actions="{ item }">
      <div v-if="item._system" />
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
              v-if="item.is_default"
              prepend-icon="mdi-refresh"
              title="Reset to Default"
              @click="$emit('reset', item)"
            ></v-list-item>
            <v-list-item
              v-if="item.may_be_stale && !item.user_managed_export"
              prepend-icon="mdi-account-check"
              title="Mark as User Managed"
              @click="$emit('mark-user-managed', item)"
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
  </v-data-table>
</template>

<script setup>
/**
 * TemplatesTable.vue — FE-6042b
 *
 * Presentational child: renders the v-data-table with all 6 item.* slots.
 * No API calls. No composables. All data flows in via props, all interactions
 * out via emits.
 *
 * Edition scope: CE
 */
import { format } from 'date-fns'
import { getAgentColor as getAgentColorConfig } from '@/config/agentColors'
import { hexToRgba } from '@/utils/colorUtils'
import { templateUpdatedState, TEMPLATE_TABLE_DEFAULT_SORT } from './templateTableConfig'

/**
 * @type {Object} props
 * @property {Array}  templates         - Filtered template rows (from filteredTemplates)
 * @property {boolean} loading          - Whether data is being loaded
 * @property {Array}  headers           - Table column definitions
 * @property {number} remainingUserSlots - Remaining activatable user slots
 * @property {number} userAgentLimit    - Max user-managed agents allowed
 */
const props = defineProps({
  /** Filtered template rows to display */
  templates: {
    type: Array,
    default: () => [],
  },
  /** Whether the table is in loading state */
  loading: {
    type: Boolean,
    default: false,
  },
  /** Column header definitions for v-data-table */
  headers: {
    type: Array,
    default: () => [],
  },
  /** Search term forwarded to v-data-table for text filtering */
  search: {
    type: String,
    default: '',
  },
  /** Number of remaining activatable user slots */
  remainingUserSlots: {
    type: Number,
    default: 0,
  },
  /** Maximum number of user-managed agents allowed */
  userAgentLimit: {
    type: Number,
    default: 7,
  },
})

defineEmits([
  'toggle-active',
  'edit',
  'duplicate',
  'reset',
  'delete',
  'mark-user-managed',
])

// ---------------------------------------------------------------------------
// Display helpers (owned by this component — used in item.* slots)
// ---------------------------------------------------------------------------

const getCategoryColor = (role) => getAgentColorConfig(role).hex

const formatDate = (date) => {
  if (!date) return 'N/A'
  return format(new Date(date), 'MMM dd, yyyy HH:mm')
}

const updatedState = (item) => templateUpdatedState(item)
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
