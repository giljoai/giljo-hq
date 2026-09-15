import { defineStore } from 'pinia'
import { ref } from 'vue'
import api from '@/services/api'
import { TASK_STATUS } from '@/utils/constants'
import { useProductStore } from './products'

export const useTaskStore = defineStore('tasks', () => {
  const productStore = useProductStore()

  const tasks = ref([])
  const loading = ref(false)
  const error = ref(null)

  let _lastFetchParams = {}

  async function fetchTasks(params = {}) {
    if (productStore.currentProductId && !params.product_id && !params.filter_type) {
      params.product_id = productStore.currentProductId
    }

    _lastFetchParams = { ...params }

    loading.value = true
    error.value = null
    try {
      const response = await api.tasks.list(params)
      tasks.value = response.data
    } catch (err) {
      error.value = err.message
      console.error('Failed to fetch tasks:', err)
    } finally {
      loading.value = false
    }
  }

  async function refreshList() {
    return fetchTasks({ ..._lastFetchParams })
  }

  async function fetchTask(id) {
    loading.value = true
    error.value = null
    try {
      const response = await api.tasks.get(id)

      const index = tasks.value.findIndex((t) => t.id === id)
      if (index !== -1) {
        tasks.value[index] = response.data
      }
    } catch (err) {
      error.value = err.message
      console.error('Failed to fetch task:', err)
    } finally {
      loading.value = false
    }
  }

  async function createTask(taskData) {
    if (!taskData.product_id && productStore.currentProductId) {
      taskData.product_id = productStore.currentProductId
    }

    loading.value = true
    error.value = null
    try {
      const response = await api.tasks.create(taskData)
      tasks.value.push(response.data)
      return response.data
    } catch (err) {
      error.value = err.message
      console.error('Failed to create task:', err)
      throw err
    } finally {
      loading.value = false
    }
  }

  async function updateTask(id, updates) {
    loading.value = true
    error.value = null
    try {
      const response = await api.tasks.update(id, updates)

      const index = tasks.value.findIndex((t) => t.id === id)
      if (index !== -1) {
        tasks.value[index] = response.data
      }

      return response.data
    } catch (err) {
      error.value = err.message
      console.error('Failed to update task:', err)
      throw err
    } finally {
      loading.value = false
    }
  }

  async function deleteTask(id) {
    loading.value = true
    error.value = null
    try {
      await api.tasks.delete(id)

      tasks.value = tasks.value.filter((t) => t.id !== id)
    } catch (err) {
      error.value = err.message
      console.error('Failed to delete task:', err)
      throw err
    } finally {
      loading.value = false
    }
  }

  async function changeTaskStatus(id, status) {
    try {
      const response = await api.tasks.changeStatus(id, status)

      const task = tasks.value.find((t) => t.id === id)
      if (task) {
        task.status = status
        task.updated_at = new Date().toISOString()

        if (status === TASK_STATUS.COMPLETED) {
          task.progress = 100
        } else if (status === TASK_STATUS.IN_PROGRESS && task.progress === 0) {
          task.progress = 50
        }
      }

      return response.data
    } catch (err) {
      console.error('Failed to change task status:', err)
      throw err
    }
  }

  function handleRealtimeUpdate(data) {
    const {
      task_id,
      project_id,
      update_type,
      title,
      description,
      status,
      assigned_to,
      priority,
      progress,
      completed_at,
    } = data

    const taskIndex = tasks.value.findIndex((t) => t.id === task_id)

    if (update_type === 'created' && taskIndex === -1) {
      const newTask = {
        id: task_id,
        project_id,
        title,
        description,
        status: status || TASK_STATUS.PENDING,
        assigned_to,
        priority: priority || 'medium',
        progress: progress || 0,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }

      tasks.value.push(newTask)
    } else if (taskIndex !== -1) {
      const task = tasks.value[taskIndex]

      if (update_type === 'status_changed' && status) {
        task.status = status
        if (status === TASK_STATUS.COMPLETED) {
          task.completed_at = completed_at || new Date().toISOString()
          task.progress = 100
        }
      }

      if (title) {
        task.title = title
      }
      if (description) {
        task.description = description
      }
      if (assigned_to !== undefined) {
        task.assigned_to = assigned_to
      }
      if (priority) {
        task.priority = priority
      }
      if (progress !== undefined) {
        task.progress = progress
      }

      task.updated_at = new Date().toISOString()
    } else if (task_id && update_type === 'created') {
      fetchTasks({ project_id })
    }
  }

  return {
    tasks,
    loading,
    error,

    fetchTasks,
    refreshList,
    fetchTask,
    createTask,
    updateTask,
    deleteTask,
    changeTaskStatus,
    handleRealtimeUpdate,
  }
})
