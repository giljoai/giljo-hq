import { ref } from 'vue'
import { useProjectStore } from '@/stores/projects'
import { useNotificationStore } from '@/stores/notifications'
import { useToast } from '@/composables/useToast'
import { notifyFailure } from '@/utils/notifyFailure'

const GENERIC_DELETE_FAILURE = 'Failed to delete project. Please try again.'
const GENERIC_CANCEL_FAILURE = 'Failed to cancel project. Please try again.'
const GENERIC_RESTORE_FAILURE = 'Failed to restore project. Please try again.'
const GENERIC_PURGE_ONE_FAILURE = 'Failed to permanently delete the project. Please try again.'
const GENERIC_PURGE_ALL_FAILURE = 'Failed to purge deleted projects. Please try again.'

export function useProjectDeletion({ showDeletedDialog, reloadProjects }) {
  const projectStore = useProjectStore()
  const notificationStore = useNotificationStore()
  const { showToast } = useToast()

  const showDeleteDialog = ref(false)
  const projectToDelete = ref(null)
  const projectToCancel = ref(null)
  const showCancelDialog = ref(false)
  const projectToPurge = ref(null)
  const showPurgeSingleDialog = ref(false)
  const showPurgeAllDialog = ref(false)

  function reportFailure(error, logLine, notice) {
    console.error(logLine, error)
    showToast({ message: notice.fallbackMessage, type: 'error' })
    notifyFailure(notificationStore, { ...notice, error })
  }

  const purgingProjectId = ref(null)
  const purgingAllDeleted = ref(false)

  function confirmDelete(project) {
    projectToDelete.value = project
    showDeleteDialog.value = true
  }

  async function deleteProject() {
    if (projectToDelete.value) {
      try {
        await projectStore.deleteProject(projectToDelete.value.id)
        showDeleteDialog.value = false
        projectToDelete.value = null
      } catch (error) {
        reportFailure(error, 'Failed to delete project:', {
          operation: 'project.delete',
          entityId: projectToDelete.value.id,
          fallbackMessage: GENERIC_DELETE_FAILURE,
          title: 'Project not deleted',
        })
      }
    }
  }

  async function executeCancelProject() {
    if (projectToCancel.value) {
      try {
        await projectStore.cancelProject(projectToCancel.value.id)
        notificationStore.clearForProject(projectToCancel.value.id)
        showCancelDialog.value = false
        projectToCancel.value = null
        await reloadProjects()
      } catch (error) {
        reportFailure(error, 'Failed to cancel project:', {
          operation: 'project.cancel',
          entityId: projectToCancel.value.id,
          fallbackMessage: GENERIC_CANCEL_FAILURE,
          title: 'Project not cancelled',
        })
      }
    }
  }

  async function restoreFromDelete(project) {
    try {
      await projectStore.restoreProject(project.id)
      showDeletedDialog.value = false
    } catch (error) {
      reportFailure(error, 'Failed to restore project:', {
        operation: 'project.restore',
        entityId: project.id,
        fallbackMessage: GENERIC_RESTORE_FAILURE,
        title: 'Project not restored',
      })
    }
  }

  function confirmPurgeDeleted(project) {
    if (!project) return
    projectToPurge.value = project
    showPurgeSingleDialog.value = true
  }

  async function purgeDeletedProject(project) {
    if (!project || purgingProjectId.value || purgingAllDeleted.value) return

    purgingProjectId.value = project.id
    try {
      await projectStore.purgeDeletedProject(project.id)
      if (projectStore.deletedProjects.length === 0) {
        showDeletedDialog.value = false
      }
    } catch (error) {
      reportFailure(error, 'Failed to purge deleted project:', {
        operation: 'project.purgeOne',
        entityId: project.id,
        fallbackMessage: GENERIC_PURGE_ONE_FAILURE,
        title: 'Project not purged',
      })
    } finally {
      purgingProjectId.value = null
    }
  }

  function confirmPurgeAllDeleted() {
    if (projectStore.deletedProjects.length === 0 || purgingAllDeleted.value) return
    showPurgeAllDialog.value = true
  }

  async function executePurgeAll() {
    showPurgeAllDialog.value = false
    purgingAllDeleted.value = true
    try {
      await projectStore.purgeAllDeletedProjects()
      showDeletedDialog.value = false
    } catch (error) {
      reportFailure(error, 'Failed to purge all deleted projects:', {
        operation: 'project.purgeAll',
        fallbackMessage: GENERIC_PURGE_ALL_FAILURE,
        title: 'Projects not purged',
      })
    } finally {
      purgingAllDeleted.value = false
      purgingProjectId.value = null
    }
  }

  return {
    showDeleteDialog,
    projectToDelete,
    projectToCancel,
    showCancelDialog,
    projectToPurge,
    showPurgeSingleDialog,
    showPurgeAllDialog,
    purgingProjectId,
    purgingAllDeleted,
    confirmDelete,
    deleteProject,
    executeCancelProject,
    restoreFromDelete,
    confirmPurgeDeleted,
    purgeDeletedProject,
    confirmPurgeAllDeleted,
    executePurgeAll,
  }
}
