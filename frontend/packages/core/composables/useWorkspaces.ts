// 工作区 = 租户。全站的数据边界,也是侧边栏最上面那一个选择器。
//
// 当前选中的工作区存在 cookie 里,不是 localStorage:服务端渲染时也要知道
// 它在哪个工作区,否则首屏画的内容和挂载后换掉的不一致。
import { computed, ref } from 'vue'
import { WorkspacesApi } from '../api/client'
import type { Workspace } from '../types/repos'

const WORKSPACE_COOKIE = 'gwei-workspace'

export function useWorkspaces() {
  const useMock = useRuntimeConfig().public.useMock === true
  const items = ref<Workspace[]>([])
  const loading = ref(true)
  const error = ref<unknown>(null)
  const picked = useCookie<string | null>(WORKSPACE_COOKIE, { default: () => null })

  async function fetch() {
    loading.value = true
    error.value = null
    try {
      if (useMock) {
        items.value = [{ slug: 'default', name: '演示工作区', repos: 3, sources: ['github'] }]
      } else {
        const res = await WorkspacesApi.list()
        items.value = res.items ?? []
      }
    } catch (e) {
      error.value = e
    } finally {
      loading.value = false
      // 选过的那个不在了(被删、换了一份库)就落回服务端说的那一个,
      // 别让界面停在一个不存在的 slug 上。
      if (!items.value.some((w) => w.slug === picked.value)) {
        picked.value = items.value[0]?.slug ?? null
      }
    }
  }

  if (import.meta.client) fetch()

  const current = computed(() => items.value.find((w) => w.slug === picked.value) ?? items.value[0])

  function select(slug: string) {
    picked.value = slug
  }

  return { items, current, picked, select, loading, error, refresh: fetch }
}
