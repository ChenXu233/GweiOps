// 仓库与项目:范围闸的两档从这两个列表里长出来。
//
// 两者都是"当前工作区里有什么"的答案,不是新的数据边界:换工作区才换一整套,
// 换档只是把同一批数据收窄。所以它们跟工作区走,不跟范围闸走。
import { computed, ref } from 'vue'
import { ProjectsApi, ReposApi } from '../api/client'
import { mockProjects, mockRepos } from '../mock'
import type { Project, Repo } from '../types/repos'

export function useRepos() {
  const useMock = useRuntimeConfig().public.useMock === true
  const { picked } = useWorkspaces()
  const repos = ref<Repo[]>([])
  const projects = ref<Project[]>([])
  const loading = ref(true)
  const error = ref<unknown>(null)

  async function fetch() {
    loading.value = true
    error.value = null
    try {
      if (useMock) {
        repos.value = mockRepos
        projects.value = mockProjects
      } else {
        const [r, p] = await Promise.all([
          ReposApi.list(picked.value ?? undefined),
          ProjectsApi.list(picked.value ?? undefined),
        ])
        repos.value = r
        projects.value = p.items ?? []
      }
    } catch (e) {
      error.value = e
    } finally {
      loading.value = false
    }
  }

  if (import.meta.client) fetch()

  /** 当前档里的仓库:选了仓库就是那一个,选了项目就是那个项目下面的。 */
  function inScope(project: string, repo: string): Repo[] {
    if (repo) return repos.value.filter((r) => r.slug === repo)
    if (project) return repos.value.filter((r) => r.project === project)
    return repos.value
  }

  return { repos, projects, loading, error, inScope, refresh: fetch }
}
