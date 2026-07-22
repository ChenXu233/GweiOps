import { ref } from 'vue'
import { ReposApi, PluginsApi } from '../api/client'
import { mockRepos, mockPlugins } from '../mock'
import type { Repo, Plugin } from '../types/repos'

const USE_MOCK = import.meta.env.NUXT_PUBLIC_USE_MOCK === 'true'

export function useRepoList() {
  const repos = ref<Repo[]>([])
  const plugins = ref<Plugin[]>([])
  const loading = ref(true)
  const error = ref<unknown>(null)

  async function fetch() {
    loading.value = true
    error.value = null
    try {
      if (USE_MOCK) {
        repos.value = mockRepos
        plugins.value = mockPlugins
      } else {
        const [r, p] = await Promise.all([ReposApi.list(), PluginsApi.list()])
        repos.value = r
        plugins.value = p
      }
    } catch (e) {
      error.value = e
    } finally {
      loading.value = false
    }
  }

  if (import.meta.client) fetch()

  return { repos, plugins, loading, error, refresh: fetch }
}
