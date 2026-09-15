<template>
  <div class="project-launch-container">
    <v-container v-if="loading" fluid class="pa-6">
      <v-row class="justify-center py-12">
        <v-col cols="12" class="text-center">
          <v-progress-circular indeterminate color="primary" size="64" />
          <p class="text-body-large mt-4">Loading project details...</p>
        </v-col>
      </v-row>
    </v-container>

    <v-container v-else-if="error" fluid class="pa-6">
      <v-row class="mb-4">
        <v-col cols="12">
          <v-alert type="error" variant="tonal" closable @click:close="error = null">
            <div>
              <p class="font-weight-bold">Error Loading Project</p>
              <p class="text-body-medium">{{ error }}</p>
            </div>
          </v-alert>
        </v-col>
      </v-row>
    </v-container>

    <div v-else class="project-content">
      <ProjectTabs
        v-if="project"
        :project="project"
        :orchestrator="orchestrator"
        :chain-ctx="chainCtx"
        @edit-description="handleEditDescription"
        @project-updated="fetchProjectDetails"
      />
    </div>

    <v-dialog v-model="showEditDialog" max-width="800" persistent scrollable>
      <v-card v-draggable class="smooth-border">
        <div class="dlg-header">
          <span class="dlg-title">Edit Project</span>
          <v-btn icon variant="text" class="dlg-close" @click="cancelEdit">
            <v-icon>mdi-close</v-icon>
          </v-btn>
        </div>

        <v-card-text>
          <v-alert type="info" variant="tonal" density="compact" class="mb-4">
            <div class="text-body-small">
              <strong>Project ID:</strong>
              <span class="ml-2 font-mono">{{ project?.id }}</span>
            </div>
          </v-alert>

          <v-form ref="projectForm" v-model="formValid">
            <v-text-field
              v-model="projectData.name"
              label="Project Name"
              :rules="[(v) => !!v || 'Project name is required']"
              required
              class="mb-3"
            ></v-text-field>

            <v-textarea
              v-model="projectData.description"
              label="Project Description"
              :rules="[(v) => !!v || 'Description is required']"
              hint="User-written description of what you want to accomplish"
              persistent-hint
              rows="4"
              required
              class="mb-3"
            ></v-textarea>

            <v-textarea
              v-model="projectData.mission"
              label="Orchestrator Mission (Optional)"
              hint="AI-generated mission created by the orchestrator"
              persistent-hint
              rows="3"
              class="mb-3"
            ></v-textarea>

          </v-form>
        </v-card-text>

        <div class="dlg-footer">
          <v-spacer></v-spacer>
          <v-btn variant="text" @click="cancelEdit">Cancel</v-btn>
          <v-btn color="primary" variant="flat" @click="saveProject">
            Update
          </v-btn>
        </div>
      </v-card>
    </v-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useToast } from '@/composables/useToast'
import { useProjectStore } from '@/stores/projects'
import { useChainContext } from '@/composables/useChainContext'
import { api } from '@/services/api'
import ProjectTabs from '@/components/projects/ProjectTabs.vue'

const route = useRoute()
const projectId = ref(route.params.projectId)
const orchestrator = ref(null)
const loading = ref(true)
const error = ref(null)

const { showToast } = useToast()
const projectStore = useProjectStore()

const { chainCtx } = useChainContext()

const project = computed(() => projectStore.projectById(projectId.value))

const showEditDialog = ref(false)
const formValid = ref(false)
const projectForm = ref(null)
const projectData = ref({
  name: '',
  description: '',
  mission: '',
})

async function fetchProjectDetails({ spinner = true } = {}) {
  if (spinner) loading.value = true
  error.value = null
  try {
    await projectStore.fetchProject(projectId.value)
    if (!project.value) {
      throw new Error(projectStore.error || 'Project not found')
    }

    const orchestratorResponse = await api.projects.getOrchestrator(projectId.value)
    orchestrator.value = orchestratorResponse.data.orchestrator
  } catch (err) {
    error.value = err.response?.data?.detail || err.message || 'Failed to load project'
  } finally {
    loading.value = false
  }
}

function handleEditDescription() {
  projectData.value = {
    name: project.value.name,
    description: project.value.description || '',
    mission: project.value.mission || '',
  }
  showEditDialog.value = true
}

async function saveProject() {
  if (typeof projectForm.value?.validate === 'function') {
    const { valid } = await projectForm.value.validate()
    if (!valid) return
  }

  try {
    const updateData = {
      name: projectData.value.name,
      description: projectData.value.description,
      mission: projectData.value.mission,
    }

    await projectStore.updateProject(projectId.value, updateData)

    showEditDialog.value = false

    showNotification('Project updated successfully', 'success')
  } catch (err) {
    console.error('Failed to update project:', err)
    showNotification(
      err.response?.data?.detail || 'Failed to update project',
      'error',
    )
  }
}

function cancelEdit() {
  showEditDialog.value = false
  projectData.value = {
    name: '',
    description: '',
    mission: '',
  }
}

function showNotification(message, color = 'success') {
  const colorToType = { success: 'success', error: 'error', info: 'info', warning: 'warning' }
  showToast({ message, type: colorToType[color] || 'info' })
}

watch(
  () => route.params.projectId,
  (newPid) => {
    if (newPid && newPid !== projectId.value) {
      projectId.value = newPid
      const warm = Boolean(projectStore.projectById(newPid))
      fetchProjectDetails({ spinner: !warm })
    }
  },
)

onMounted(() => {
  fetchProjectDetails()
})
</script>

<style scoped>
/* Project Launch Container - Full height layout */
.project-launch-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0; /* Critical for flex overflow */
}

/* Main content area - fills remaining space */
.project-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0; /* Critical for nested flex overflow */
  overflow: hidden; /* Let ProjectTabs handle scrolling */
}
</style>
