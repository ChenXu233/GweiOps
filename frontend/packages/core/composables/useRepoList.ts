import { ref } from 'vue'
import { ReposApi, PluginsApi } from '../api/client'
import { mockRepos, mockPlugins } from '../mock'
import type { Repo, Plugin } from '../types/repos'
import type { PluginManifestDTO } from '../types/plugin'

const USE_MOCK = import.meta.env.NUXT_PUBLIC_USE_MOCK === 'true'

// engine 清单 DTO → 前端 Plugin 形状(市场卡片所需字段)
function toPlugin(m: PluginManifestDTO): Plugin {
  return {
    id: m.name,
    name: m.name,
    icon: '🧩',
    description: m.description,
    author: 'official',
    price: null,
    installed: true,
    pageTitle: m.pages?.[0]?.title,
  }
}

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
        const [r, manifests] = await Promise.all([ReposApi.list(), PluginsApi.manifests()])
        repos.value = r
        plugins.value = manifests.map(toPlugin)
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
