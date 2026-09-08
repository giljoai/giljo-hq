<template>
  <v-dialog v-model="isOpen" max-width="800" persistent retain-focus scrollable>
    <v-card v-draggable class="smooth-border">
      <div class="dlg-header">
        <span class="dlg-title">{{ editingProject ? 'Edit Project' : 'Create New Project' }}</span>
        <AgentTipsDialog />
        <v-btn icon variant="text" class="dlg-close" aria-label="Close dialog" @click="cancel">
          <v-icon>mdi-close</v-icon>
        </v-btn>
      </div>

      <v-card-text>
        <!-- Save Error Alert (Handover 0440d) -->
        <v-alert
          v-if="saveError"
          type="error"
          variant="tonal"
          density="compact"
          class="mb-4"
          closable
          @click:close="saveError = ''"
        >
          {{ saveError }}
        </v-alert>

        <!-- Success Alert -->
        <v-alert
          v-if="createdProjectId"
          type="success"
          variant="tonal"
          density="compact"
          class="mb-4"
          closable
        >
          <div class="text-body-medium mb-1">Project created successfully!</div>
          <div class="text-body-small">
            <strong>Project ID:</strong>
            <span class="ml-2 font-mono">{{ createdProjectId }}</span>
          </div>
        </v-alert>

        <!-- Project metadata (plain text, no alert box) -->
        <div v-if="editingProject" class="text-body-small text-muted-a11y mb-4">
          <div>Project ID: <span class="font-mono">{{ editingProject.id }}</span></div>
          <div>
            Created: {{ formatDateTime(editingProject.created_at) }}
            <span class="mx-2">|</span>
            Updated: {{ formatDateTime(editingProject.updated_at) }}
          </div>
        </div>

        <!-- Form -->
        <v-form ref="projectFormRef" v-model="formValid">
          <!-- Taxonomy Row: Type | Serial # | Suffix (Handover 0440c) -->
          <v-row density="comfortable" class="mb-1 align-start">
            <!-- Type Dropdown -->
            <v-col cols="5">
              <v-select
                v-model="localData.project_type_id"
                :items="typeDropdownItems"
                label="Type"
                item-title="display"
                item-value="id"
                density="compact"
                variant="outlined"
                clearable
                hide-details
                aria-label="Project type"
                @update:model-value="handleTypeChange"
              >
                <template #item="{ props: itemProps, item }">
                  <v-list-item v-if="item.id === '__add_custom__'" v-bind="itemProps" @click.stop="showAddTypeModal = true">
                    <template #prepend>
                      <v-icon size="small">mdi-plus-circle</v-icon>
                    </template>
                  </v-list-item>
                  <v-list-item v-else v-bind="itemProps" :disabled="item.disabled">
                    <template #prepend>
                      <div :style="{ backgroundColor: item.color, width: '12px', height: '12px', borderRadius: '50%' }" />
                    </template>
                  </v-list-item>
                </template>
                <template #selection="{ item }">
                  <div class="d-flex align-center">
                    <div :style="{ backgroundColor: item.color, width: '10px', height: '10px', borderRadius: '50%', marginRight: '6px' }" />
                    {{ item.abbreviation }}
                  </div>
                </template>
              </v-select>
            </v-col>

            <!-- Serial Number Text Input -->
            <v-col cols="4">
              <v-text-field
                v-model="seriesNumberInput"
                label="Serial #"
                density="compact"
                variant="outlined"
                maxlength="6"
                :error="seriesCheckResult === false"
                :color="seriesCheckResult === true ? 'success' : undefined"
                :messages="seriesCheckMessage"
                :loading="seriesChecking"
                placeholder="0001"
                aria-label="Series number"
                @update:model-value="onSeriesInput"
              >
                <template #append-inner>
                  <v-icon v-if="seriesCheckResult === true" color="success" size="small">mdi-check-circle</v-icon>
                  <v-icon v-else-if="seriesCheckResult === false" color="error" size="small">mdi-close-circle</v-icon>
                </template>
              </v-text-field>
            </v-col>

            <!-- Suffix Dropdown (only shows available letters) -->
            <v-col cols="3">
              <v-select
                v-model="localData.subseries"
                :items="subseriesItems"
                label="Suffix"
                item-title="title"
                item-value="value"
                density="compact"
                variant="outlined"
                clearable
                hide-details
                :disabled="!localData.series_number"
                aria-label="Subseries suffix"
                @update:model-value="onSubseriesChange"
              />
            </v-col>
          </v-row>

          <!-- Project Name -->
          <v-text-field
            v-model="localData.name"
            label="Project Name"
            :rules="[(v) => !!v || 'Project name is required']"
            required
            density="compact"
            variant="outlined"
            hide-details="auto"
            maxlength="255"
            counter="255"
            class="mb-3"
            aria-label="Project name"
          />

          <v-textarea
            v-model="localData.description"
            label="Project Description"
            :rules="[(v) => !!v || 'Description is required']"
            hint="User-written description of what you want to accomplish. This will be shown to the orchestrator."
            :persistent-hint="descriptionHintPersistent"
            rows="4"
            required
            class="mb-3"
            aria-label="Project description"
          ></v-textarea>

          <v-textarea
            v-model="localData.mission"
            label="Orchestrator Generated Mission"
            readonly
            variant="outlined"
            rows="4"
            class="mb-3"
            hint="Auto-generated during staging. Clear to regenerate on next staging."
            persistent-hint
            :placeholder="
              localData.mission ? '' : 'Mission will be generated when you stage this project'
            "
            aria-label="Orchestrator generated mission"
          >
            <template #append>
              <v-menu>
                <template #activator="{ props }">
                  <v-btn
                    icon="mdi-dots-vertical"
                    v-bind="props"
                    size="small"
                    variant="text"
                    aria-label="Mission actions"
                  />
                </template>
                <v-list>
                  <v-list-item :disabled="!localData.mission" @click="viewFullMission">
                    <v-list-item-title>View Full Mission</v-list-item-title>
                  </v-list-item>
                  <v-list-item :disabled="!localData.mission" @click="$emit('clear-mission')">
                    <v-list-item-title>Clear Mission</v-list-item-title>
                  </v-list-item>
                </v-list>
              </v-menu>
            </template>
          </v-textarea>
        </v-form>

        <!-- Add Type Modal (Handover 0440c) -->
        <AddTypeModal v-model="showAddTypeModal" @type-created="handleTypeCreated" />
      </v-card-text>

      <div class="dlg-footer">
        <v-spacer></v-spacer>
        <v-btn variant="text" @click="cancel">Cancel</v-btn>
        <v-btn color="primary" variant="flat" @click="save">
          {{ editingProject ? 'Update' : 'Create' }}
        </v-btn>
      </div>
    </v-card>
  </v-dialog>

  <!-- Mission Viewer Dialog -->
  <v-dialog v-model="showMissionDialog" max-width="800" persistent retain-focus scrollable>
    <v-card v-draggable class="smooth-border">
      <div class="dlg-header">
        <span class="dlg-title">Full Mission Text</span>
        <v-btn icon variant="text" class="dlg-close" aria-label="Close dialog" @click="showMissionDialog = false">
          <v-icon>mdi-close</v-icon>
        </v-btn>
      </div>

      <v-card-text>
        <v-sheet
          class="pa-4 rounded smooth-border mission-viewer-sheet"
          color="grey-lighten-5"
        >
          {{ localData.mission || 'No mission text available' }}
        </v-sheet>
      </v-card-text>

      <div class="dlg-footer">
        <v-spacer></v-spacer>
        <v-btn variant="text" @click="showMissionDialog = false">Close</v-btn>
      </div>
    </v-card>
  </v-dialog>
</template>

<script setup>
import { ref, watch, computed } from 'vue'
import { useProjectStore } from '@/stores/projects'
import AddTypeModal from '@/components/projects/AddTypeModal.vue'
import AgentTipsDialog from '@/components/common/AgentTipsDialog.vue'
import api from '@/services/api'
import { useFormatDate } from '@/composables/useFormatDate'
import { useProjectTaxonomy } from '@/composables/useProjectTaxonomy'

const props = defineProps({
  modelValue: {
    type: Boolean,
    required: true,
  },
  editingProject: {
    type: Object,
    default: null,
  },
  activeProduct: {
    type: Object,
    default: null,
  },
  projectTypes: {
    type: Array,
    default: () => [],
  },
})

const emit = defineEmits(['update:modelValue', 'saved', 'clear-mission', 'type-created'])

const projectStore = useProjectStore()
const { formatDateTime } = useFormatDate()

const isOpen = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val),
})

const projectFormRef = ref(null)
const formValid = ref(false)
const saveError = ref('')
const createdProjectId = ref(null)
const showMissionDialog = ref(false)

const localData = ref({
  name: '',
  description: '',
  mission: '',
  status: 'inactive',
  project_type_id: null,
  series_number: null,
  subseries: null,
})

const projectTypesRef = computed(() => props.projectTypes)
const editingProjectRef = computed(() => props.editingProject)
// FE-9502c: scope series-number lookups to the caller-supplied product (the
// viewed tab, per ProjectsView.vue), not whichever product happens to be
// server-active.
const productIdRef = computed(() => props.activeProduct?.id || null)

// The Description hint persists only while the field has content. When the field
// is empty — the only state where the "Description is required" error fires — the
// hint stops persisting so it can't overlap the error text in the details row.
const descriptionHintPersistent = computed(() => !!localData.value.description)

const {
  showAddTypeModal,
  seriesNumberInput,
  seriesChecking,
  seriesCheckResult,
  seriesCheckMessage,
  usedSubseries,
  typeDropdownItems,
  subseriesItems,
  handleTypeChange,
  handleTypeCreated: handleTypeCreatedInternal,
  onSeriesInput,
  onSubseriesChange,
  resetTaxonomy,
} = useProjectTaxonomy({
  projectTypes: projectTypesRef,
  projectData: localData,
  editingProject: editingProjectRef,
  productId: productIdRef,
})

function handleTypeCreated(newType) {
  handleTypeCreatedInternal(newType)
  emit('type-created', newType)
}

watch(
  () => props.modelValue,
  async (opened) => {
    if (opened) {
      saveError.value = ''
      createdProjectId.value = null
      if (props.editingProject) {
        const project = props.editingProject
        localData.value = {
          name: project.name,
          description: project.description || '',
          mission: project.mission,
          status: project.status,
          project_type_id: project.project_type_id || null,
          series_number: project.series_number || null,
          subseries: project.subseries || null,
        }
        seriesNumberInput.value = project.series_number
          ? String(project.series_number).padStart(4, '0')
          : ''
        if (project.series_number && project.project_type_id) {
          seriesCheckResult.value = true
          seriesCheckMessage.value = 'Current value'
          try {
            const { data } = await api.projects.usedSubseries(
              project.project_type_id,
              project.series_number,
              project.id,
              {},
              productIdRef.value,
            )
            usedSubseries.value = data.used_subseries || []
          } catch {
            usedSubseries.value = []
          }
        } else {
          seriesCheckResult.value = null
          seriesCheckMessage.value = ''
          usedSubseries.value = []
        }
      } else {
        resetForm()
      }
    }
  },
)

// Expose clearMission so parent can call it after confirming the clear-mission dialog
function clearMissionData() {
  localData.value.mission = ''
}

function viewFullMission() {
  showMissionDialog.value = true
}

function resetForm() {
  localData.value = {
    name: '',
    description: '',
    mission: '',
    status: 'inactive',
    project_type_id: null,
    series_number: null,
    subseries: null,
  }
  resetTaxonomy()
  saveError.value = ''
}

function cancel() {
  isOpen.value = false
  resetForm()
}

async function save() {
  // Validate ON CLICK rather than silently disabling the button. A disabled
  // "Create" gave the user NO feedback about what was wrong: Vuetify only shows
  // a required-field error once the field is touched, so an untouched-but-empty
  // Description left Create greyed out with zero indication why (perf-findings
  // 2026-06-11 UX bug — same felt-failure class as task-create). validate()
  // surfaces "Description is required" on the field so the blocker is visible.
  const { valid } = await projectFormRef.value.validate()
  if (!valid) return

  try {
    if (props.editingProject) {
      const updateData = {
        name: localData.value.name,
        description: localData.value.description,
        mission: localData.value.mission,
        status: localData.value.status,
        project_type_id: localData.value.project_type_id,
        series_number: localData.value.series_number,
        subseries: localData.value.subseries,
      }
      await projectStore.updateProject(props.editingProject.id, updateData)
      await projectStore.fetchProjects()

      isOpen.value = false
      resetForm()
      emit('saved', { action: 'updated' })
    } else {
      const createData = {
        ...localData.value,
        product_id: props.activeProduct?.id,
      }
      const result = await projectStore.createProject(createData)
      createdProjectId.value = result.id
      await projectStore.fetchProjects()

      setTimeout(() => {
        isOpen.value = false
        createdProjectId.value = null
        resetForm()
        formValid.value = false
        emit('saved', { action: 'created', id: result.id })
      }, 2000)
    }
  } catch (error) {
    console.error('[PROJECTS][CreateProject] Failed to save project:', error)
    saveError.value = error.response?.data?.error || error.message || 'Failed to save project'
  }
}

defineExpose({ clearMissionData })
</script>

<style lang="scss" scoped>
@use '../../styles/design-tokens' as *;

.mission-viewer-sheet {
  max-height: 500px;
  overflow-y: auto;
  white-space: pre-wrap;
  font-family: monospace;
  font-size: 0.875rem;
  line-height: 1.5;
}
</style>
