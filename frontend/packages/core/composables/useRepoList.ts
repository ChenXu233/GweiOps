import { computed, ref } from 'vue'
import { ReposApi, PluginsApi } from '../api/client'
import { mockRepos, mockPlugins } from '../mock'
import type { Repo, Plugin } from '../types/repos'
import type { PluginManifestDTO } from '../types/plugin'

/** engine 清单 DTO → 前端 Plugin 形状。`enabled` 取引擎给的值。 */
function toPlugin(m: PluginManifestDTO): Plugin {
  return {
    id: m.name,
    name: m.name,
    description: m.description,
    author: 'official',
    price: null,
    enabled: m.enabled === true,
    platform_available: m.platform_available !== false,
    tenant_enabled: m.tenant_enabled !== false,
    reason: m.reason ?? '',
    error: m.error ?? '',
    instances: m.instances ?? [],
    version: m.version,
    type: m.type,
    capabilities: m.capabilities ?? [],
    pageTitle: m.pages?.[0]?.title || undefined,
  }
}

export function useRepoList() {
  const useMock = useRuntimeConfig().public.useMock === true
  const repos = ref<Repo[]>([])
  const plugins = ref<Plugin[]>([])
  const loading = ref(true)
  const error = ref<unknown>(null)

  async function fetch() {
    loading.value = true
    error.value = null
    try {
      if (useMock) {
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

  const toggling = ref<string | null>(null)
  const actionError = ref('')

  async function setEnabled(name: string, enabled: boolean) {
    toggling.value = name
    actionError.value = ''
    try {
      if (enabled) await PluginsApi.enable(name)
      else await PluginsApi.disable(name)
      await fetch()
    } catch (e) {
      actionError.value = e instanceof Error ? e.message : String(e)
    } finally {
      toggling.value = null
    }
  }

  async function rescan() {
    toggling.value = '*'
    actionError.value = ''
    try {
      await PluginsApi.rescan()
      await fetch()
    } catch (e) {
      actionError.value = e instanceof Error ? e.message : String(e)
    } finally {
      toggling.value = null
    }
  }

  const enabledCount = computed(() => plugins.value.filter((p) => p.enabled).length)

  return {
    repos,
    plugins,
    enabledCount,
    loading,
    error,
    actionError,
    toggling,
    setEnabled,
    rescan,
    refresh: fetch,
  }
}
