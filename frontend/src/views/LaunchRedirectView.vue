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
    <!-- FE-9548: D8 bans "Active"/"Activate" -- matches the Jobs board's own
         empty state (jobs-board-proposal-v4.html) so the two surfaces read as
         one vocabulary. -->
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

// FE-9533: read the store's reactive activeProjectsMeta instead of a one-shot
// direct api.projects.getActive() call into a local ref. The old version
// bypassed the projects store entirely, so it had no way to notice a project
// becoming active while this page sat idle on "No Active Project" — the
// operator had to reload. activeProjectsMeta is kept live by the store's own
// project_update/status_changed WS handler (handleRealtimeUpdate), the same
// mechanism the Projects list already relies on, so this pane now updates the
// same way.
//
// FE-9525d: BE-9525a/b retired the single-active-project-per-product
// invariant, so this list can now hold more than one row. ONE active project
// still redirects straight to it (byte-identical to before this project);
// SEVERAL redirect to the sectioned Jobs viewport instead.
const activeProjects = computed(() => projectStore.activeProjectsMeta)
const activeProject = computed(() => activeProjects.value[0] ?? null)

// `immediate: true` covers BOTH the redirect-on-mount case (once the initial
// fetch below resolves and activeProjects flips from empty to non-empty) and
// the live case (activeProjects flips later, on a WS event, with this view
// still mounted) — one code path for both, matching the DoD: update in place,
// never a poll.
watch(
  activeProjects,
  (projects) => {
    if (projects.length > 1) {
      router.replace({ name: 'JobsViewport' })
    } else if (projects.length === 1) {
      // Redirect to the dynamic project route and tag source for sidebar highlighting
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
    // No active project (or a transient fetch error, which fetchActiveProject
    // already logs and treats as none) — show the "no active project" page.
    // A later WS-driven change to activeProject is picked up by the watcher
    // above without needing this flag again.
    loading.value = false
  }
})
</script>
