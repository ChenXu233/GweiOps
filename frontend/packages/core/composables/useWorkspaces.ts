// 工作区 = 租户。全站的数据边界,也是侧边栏最上面那一个选择器。
//
// 当前工作区**不在 cookie 里**:它在路径里。`/api/workspaces/{slug}/…` 是唯一
// 能改数据的入口,所以界面这边也跟着走 —— 服务端渲染时首屏就是对的,分享出去的
// 链接也自带"这是哪一道账"。
//
// 一个只属于一个工作区的人,链接里用不着每次都带那一段:引擎在没有工作区段时按他
// 最早的那条成员关系回答。
import { computed } from 'vue'
import { WorkspacesApi } from '../api/client'
import { setWorkspaceScope } from '../api/typed'
import type { Workspace } from '../types/repos'

// 一次请求,所有调用点共用:一页里有五六个组件问"有哪些工作区",不该发五次。
// fetch 只在客户端跑(服务端首屏用不到这份列表),所以这个模块级变量不会在
// 并发的 SSR 请求之间串账。
let inFlight: Promise<void> | null = null

export function useWorkspaces() {
  // 服务端每个请求一份:模块级的 ref 会让并发的 SSR 请求互相串账 —— 渲染出来的
  // 链接可能指着另一个请求的工作区。客户端上它就是全站共享的那一份。
  const currentSlug = useState<string>('gwei-workspace-slug', () => '')
  const useMock = useRuntimeConfig().public.useMock === true
  // 列表、加载态、错误也只存一份:每个组件各拉一批,不但多几次请求,各处对
  // "当前有哪些工作区"还会读到不同批的数据。
  const items = useState<Workspace[]>('gwei-workspaces', () => [])
  const loading = useState<boolean>('gwei-workspaces-loading', () => true)
  const error = useState<unknown>('gwei-workspaces-error', () => null)

  // 每个调用点都走这一层:路径里的工作区段由它补,调用点不必自己拼。
  setWorkspaceScope(() => currentSlug.value)

  async function fetch(): Promise<void> {
    // 服务端不拉这份列表:首屏用不到,也省一次请求。调用点都在客户端。
    if (import.meta.server) return
    if (inFlight) return inFlight
    const run = (async () => {
      loading.value = true
      error.value = null
      try {
        if (useMock) {
          items.value = [{ slug: 'default', name: '演示工作区', repos: 3, sources: ['github'] }]
        } else {
          // 列表只列我进得去的那几个 —— 列一个进不去的,只会给出"它在但你不能点"
          const res = await WorkspacesApi.list()
          items.value = res.items ?? []
        }
      } catch (e) {
        error.value = e
      } finally {
        loading.value = false
        // 手里的那个不在了(被移出、换了一份库)就落回服务端给的那一个,
        // 别让界面停在一个不存在的 slug 上。
        if (!items.value.some((w) => w.slug === currentSlug.value)) {
          currentSlug.value = items.value[0]?.slug ?? ''
        }
      }
    })()
    // finally 也返回一个新 promise:等这次真正结束再放开下一次。
    inFlight = run.finally(() => {
      inFlight = null
    })
    return inFlight
  }

  /**
   * 这次页面渲染落在哪个工作区。
   *
   * 前端路由不重复后端的 `/api/workspaces`:`/workspaces/{slug}/issues` 是界面上的
   * 那一段,页面挂载时把它抄进来。链接自带工作区,刷新与分享都还是同一道账。
   */
  function syncFromRoute() {
    const route = useRoute()
    const parts = route.path.split('/').filter(Boolean)
    if (parts[0] !== 'workspaces' || !parts[1]) return
    if (currentSlug.value !== parts[1]) {
      currentSlug.value = parts[1]
      // 换了工作区就是换了一整套数据:留在原页面上等于看一个不属于这个工作区的列表。
      if (import.meta.client) fetch()
    }
  }

  /** 某个工作区里的某条界面路径。选择器与页面跳转都该用它,别自己拼。 */
  function hrefFor(path: string, slug = currentSlug.value): string {
    if (!slug) return path
    return `/workspaces/${encodeURIComponent(slug)}${path.startsWith('/') ? path : `/${path}`}`
  }

  if (import.meta.client) fetch()

  const current = computed(
    () => items.value.find((w) => w.slug === currentSlug.value) ?? items.value[0],
  )

  /** 换工作区。选择器用:它换的不是"看哪个列表",是数据边界。 */
  function select(slug: string) {
    currentSlug.value = slug
  }

  return {
    items,
    current,
    picked: currentSlug,
    select,
    hrefFor,
    loading,
    error,
    refresh: fetch,
    syncFromRoute,
  }
}
