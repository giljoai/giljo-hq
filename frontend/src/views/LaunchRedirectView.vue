<template>
  <div v-if="loading" class="d-flex justify-center align-center" style="height: 100vh">
    <v-progress-circular indeterminate size="64" color="primary"></v-progress-circular>
  </div>

  <div
    v-else-if="!redirectTarget"
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
import { useProductStore } from '@/stores/products'
import { useSequenceRunStore } from '@/stores/sequenceRunStore'
import { resolveJobsNavPath, jobsNavPathToLocation } from '@/utils/jobsNavTarget'

const router = useRouter()
const loading = ref(true)
const projectStore = useProjectStore()
const productStore = useProductStore()
const sequenceRunStore = useSequenceRunStore()

const scopedFetchSettled = ref(false)

const activeProjects = computed(() => projectStore.activeProjectsMeta)
const activeProject = computed(() => activeProjects.value[0] ?? null)
const activeRun = computed(() => sequenceRunStore.activeRuns[0] ?? sequenceRunStore.reviewPendingRun ?? null)

const redirectTarget = computed(() =>
  jobsNavPathToLocation(
    resolveJobsNavPath({
      activeProject: activeProject.value,
      activeProjects: activeProjects.value,
      activeRun: activeRun.value,
    }),
  ),
)

watch(
  [redirectTarget, scopedFetchSettled],
  ([target, settled]) => {
    if (!settled || !target) return
    router.replace(target)
  },
  { immediate: true },
)

async function loadForViewedProduct() {
  try {
    await Promise.allSettled([projectStore.fetchActiveProject(), sequenceRunStore.hydrate()])
  } finally {
    scopedFetchSettled.value = true
    loading.value = false
  }
}

watch(
  () => productStore.effectiveProductId,
  () => {
    scopedFetchSettled.value = false
    loading.value = true
    loadForViewedProduct()
  },
)

onMounted(loadForViewedProduct)
</script>
