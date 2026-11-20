import { onMounted, ref } from 'vue'
import { ChangesApi, IssuesApi } from '../api/client'
import { mockTimelineFor } from '../mock'
import type { IssueTimeline } from '../types/issues'

/** 议题详情上能做的三件事。继续改不在其中:它开的是新一轮执行,不是改这一条。 */
export type TimelineAction = 'approve' | 'veto' | 'rollback'

// 写进账本的理由:谁在哪儿放的手,事后要能查。
const REASON: Record<TimelineAction, string> = {
  approve: '人工放行(议题详情)',
  veto: '人工否决(议题详情)',
  rollback: '人工回滚(议题详情)',
}

export function useIssueTimeline(id: string) {
  const useMock = useRuntimeConfig().public.useMock === true
  const data = ref<IssueTimeline | null>(null)
  const loading = ref(true)
  const error = ref<string | null>(null)
  // 正在操作的那个单元:按钮就地转圈,不把整页变灰
  const busy = ref<string | null>(null)

  function fail(e: unknown) {
    error.value = e instanceof Error ? e.message : String(e)
  }

  async function refresh() {
    // 地址里没有编号就不发请求:那会打到 /api/issues//timeline,引擎回的 404
    // 跟"这条议题不存在"分不开,界面只能说一句看不懂的错误。
    if (!id) {
      loading.value = false
      error.value = '这个地址里没有议题编号'
      return
    }
    if (!data.value) loading.value = true
    error.value = null
    try {
      data.value = useMock ? mockTimelineFor(id) : await IssuesApi.timeline(id)
    } catch (e) {
      fail(e)
    } finally {
      loading.value = false
    }
  }

  /** 放行 / 否决 / 撤销。做完立刻重读时间线:结论必须来自账本,不由本地改。 */
  async function act(unitId: string, action: TimelineAction) {
    if (!unitId) return
    busy.value = unitId
    error.value = null
    try {
      if (!useMock) await ChangesApi[action](unitId, REASON[action])
      await refresh()
    } catch (e) {
      fail(e)
    } finally {
      busy.value = null
    }
  }

  /** 接着这条线再改一轮。轮次不在这里拼:它跑起来之后由后端给。 */
  async function continueRound(instruction: string) {
    const text = instruction.trim()
    if (!text) return
    busy.value = 'continue'
    error.value = null
    try {
      if (useMock) {
        // 演示模式没有引擎,这一轮不会真的开。宁可说清楚,也不要假装排队了。
        throw new Error('演示模式没有引擎:这一轮不会真的开。')
      }
      await IssuesApi.continueRound(id, text)
      await refresh()
    } catch (e) {
      fail(e)
      throw e
    } finally {
      busy.value = null
    }
  }

  // 挂载后再拉:首屏与服务端渲染保持一致。演示模式的数据是同步给出的,
  // 在 setup 里直接填会变成"服务端是骨架、客户端是内容"——hydrate 当场对不上。
  onMounted(() => refresh())

  return { data, loading, error, busy, refresh, act, continueRound }
}
