import { onMounted, ref } from 'vue'
import { IssuesApi } from '../api/client'
import { mockIssueBoard } from '../mock'
import type { IssueBoard } from '../types/issues'

/**
 * 首页那张议题板。三个状态与三个数都由后端给:前端不按 issue 状态自己分组,
 * 那两套口径一旦不同,列表说"落了"、点进去说"等你",最难查。
 */
export function useIssueBoard() {
  const useMock = useRuntimeConfig().public.useMock === true
  const data = ref<IssueBoard | null>(null)
  const loading = ref(true)
  const error = ref<string | null>(null)

  async function refresh() {
    if (!data.value) loading.value = true
    error.value = null
    try {
      data.value = useMock ? mockIssueBoard : await IssuesApi.board(200)
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }

  onMounted(() => refresh())

  return { data, loading, error, refresh }
}
