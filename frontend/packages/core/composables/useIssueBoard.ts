import { ref, watch } from 'vue'
import { IssuesApi } from '../api/client'
import { mockIssueBoard } from '../mock'
import type { IssueBoard } from '../types/issues'

/**
 * 首页那张议题板。三个状态与三个数都由后端给:前端不按 issue 状态自己分组,
 * 那两套口径一旦不同,列表说"落了"、点进去说"等你",最难查。
 *
 * 范围闸的三档(工作区 / 项目 / 仓库)也在后端收:前端只是把档传上去,不自己
 * 过滤一份。筛在客户端意味着两套"这一行算不算在范围内"的判定,迟早对不上。
 */
export function useIssueBoard() {
  const useMock = useRuntimeConfig().public.useMock === true
  const { project, repo } = useScope()
  const data = ref<IssueBoard | null>(null)
  const loading = ref(true)
  const error = ref<string | null>(null)

  async function refresh() {
    if (!data.value) loading.value = true
    error.value = null
    try {
      if (useMock) {
        data.value = mockIssueBoard
      } else {
        data.value = await IssuesApi.board({
          limit: 200,
          // 工作区在路径里(typed.ts 的 scopePath 补),查询串不再说一次
          project: project.value || undefined,
          repo: repo.value || undefined,
        })
      }
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }

  // 换档 / 换工作区就是换一页数据:留着上一档的列表先画出来,会让人以为新范围
  // 里也有那些。`immediate`,首屏那次也走这里,不再另起一个挂载钩子。
  watch([project, repo], () => {
    data.value = null
    if (import.meta.client) refresh()
  }, { immediate: true })

  return { data, loading, error, refresh }
}
