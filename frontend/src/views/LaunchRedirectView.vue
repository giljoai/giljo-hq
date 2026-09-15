<template>
  <div v-if="loading" class="d-flex justify-center align-center" style="height: 100vh">
    <v-progress-circular indeterminate size="64" color="primary"></v-progress-circular>
  </div>

  <div
    v-else-if="!activeProject"
    class="d-flex flex-column justify-center align-center"
    style="height: 100vh"
  >
    <v-icon size="96" color="grey-darken-2">mdi-briefcase-off-outline</v-icon>
    <h2 class="text-headline-large mt-4 text-grey-darken-2">Nothing in flight for this product</h2>
    <p class="text-body-large mt-2 text-grey">Stage a project to see its agents here.</p>
    <v-btn color="primary" class="mt-6" to="/projects"> Go to Projects </v-btn>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useProjectStore } from '@/stores/projects'

const router = useRouter()
const loading = ref(true)
const projectStore = useProjectStore()

const activeProjects = computed(() => projectStore.activeProjectsMeta)
const activeProject = computed(() => activeProjects.value[0] ?? null)

watch(
  activeProjects,
  (projects) => {
    if (projects.length > 1) {
      router.replace({ name: 'JobsViewport' })
    } else if (projects.length === 1) {
      router.replace({
        name: 'ProjectLaunch',
        params: { projectId: projects[0].id },
        query: { via: 'jobs' },
      })
    }
  },
  { immediate: true },
)

onMounted(async () => {
  try {
    await projectStore.fetchActiveProject()
  } finally {
    loading.value = false
  }
})
</script>
