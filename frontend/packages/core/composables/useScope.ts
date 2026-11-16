// 范围闸:议题板收窄到哪一档。
//
// 三档 —— 整个工作区 → 某个项目 → 某个仓库 —— 是**同一个筛选器**上的三个位置,
// 不是三段导航。仓库一多就把项目做成侧边栏的可展开分组,导航长度会跟着数据
// 变长:那是数据决定结构,已经否过一次了。
//
// 选中的档记在 URL 查询串里,不记 cookie:范围是"我现在在看什么",刷新、分享、
// 从详情页点回来都该保持;而工作区是数据边界,那是 cookie 的事。
import { computed } from 'vue'

export function useScope() {
  // Nuxt 的自动导入:core 包里不直接依赖 vue-router 的类型包。
  const route = useRoute()
  const router = useRouter()

  const project = computed(() => String(route.query.project ?? ''))
  const repo = computed(() => String(route.query.repo ?? ''))

  /** 换档。给空串 = 回到上一档。 */
  async function setScope(next: { project?: string; repo?: string }) {
    const query = { ...route.query }
    for (const key of ['project', 'repo'] as const) {
      const value = next[key]
      if (value === undefined) continue
      if (value) query[key] = value
      else delete query[key]
    }
    await router.replace({ query })
  }

  /** 把查询串原样带上:链接跳出去再回来,档还在。 */
  function withScope(path: string): string {
    const q = new URLSearchParams()
    if (project.value) q.set('project', project.value)
    if (repo.value) q.set('repo', repo.value)
    const s = q.toString()
    return s ? `${path}?${s}` : path
  }

  return { project, repo, setScope, withScope }
}
