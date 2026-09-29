import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { parseErrorResponse } from '@/utils/errorMessages'

export function useTokenActionPage(performAction) {
  const route = useRoute()
  const router = useRouter()

  const loading = ref(true)
  const success = ref(false)
  const response = ref(null)
  const errorDetail = ref('')

  const token = computed(() => route.query.token || '')
  const tokenMissing = computed(() => !token.value)

  function goLogin() {
    router.push('/login')
  }

  onMounted(async () => {
    if (tokenMissing.value) {
      loading.value = false
      return
    }
    try {
      response.value = await performAction(token.value)
      success.value = true
    } catch (err) {
      errorDetail.value = parseErrorResponse(err).message
      success.value = false
    } finally {
      loading.value = false
    }
  })

  return { loading, success, response, errorDetail, token, tokenMissing, goLogin }
}
