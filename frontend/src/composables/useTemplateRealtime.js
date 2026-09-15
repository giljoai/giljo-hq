import { onMounted, onUnmounted } from 'vue'

export function useTemplateRealtime(templates, reloadActiveCount) {
  const handleTemplateUpdated = (data) => {
    if (!data?.template_id) return
    const template = templates.value.find((t) => t.id === data.template_id)
    if (template) {
      if (data.is_active !== undefined) template.is_active = data.is_active
      if (data.updated_fields?.includes('is_active')) reloadActiveCount()
    }
  }

  const onTemplateUpdated = (e) => handleTemplateUpdated(e.detail)

  onMounted(() => {
    window.addEventListener('template:updated', onTemplateUpdated)
  })

  onUnmounted(() => {
    window.removeEventListener('template:updated', onTemplateUpdated)
  })

  return { handleTemplateUpdated }
}
