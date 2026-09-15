
import { defineStore } from 'pinia'

export const useProjectTabsStore = defineStore('projectTabs', {
  state: () => ({
    currentProject: null,
    isLaunched: false,
  }),

  actions: {
    setCurrentProject(project) {
      this.currentProject = project || null
    },

    setLaunched(isLaunched) {
      this.isLaunched = Boolean(isLaunched)
    },

    $reset() {
      this.currentProject = null
      this.isLaunched = false
    },
  },
})
