import { computed, ref } from 'vue'
import { SignalsApi } from '../api/signals'
import { mockSignalPlugins, mockSignalRepos } from '../mock/signals'
import type { PluginManifestDTO } from '../types/plugin'
import type { Repo } from '../types/repos'
import type { CapabilityGroup, CapabilityProvider, SignalEntry } from '../types/signals'

/**
 * 接入口:引擎里真实存在的两个 POST 路径。
 * 事件与租户行为照 engine/api/routes/webhook.py 写:
 * - /webhook/github        收 issues / issue_comment,ping 直接回 pong
 * - /webhook/github/comment 只收 issue_comment,且正文必须带 @gwei
 * 租户不是投递方指定的:引擎用默认租户入队,并把 tenant_slug 写进工作流载荷顶层。
 */
export const SIGNAL_ENTRIES: SignalEntry[] = [
  {
    path: '/webhook/github',
    method: 'POST',
    title: '议题事件',
    events: 'issues(动作 opened / edited);另外接受 issue_comment 与 ping(回 pong)',
    tenant: '引擎写进工作流载荷的顶层 tenant_slug,当前是默认租户 default',
    handoff: '验签 → 去重 → 按租户入队,之后由工作流接管',
  },
  {
    path: '/webhook/github/comment',
    method: 'POST',
    title: '评论事件',
    events: 'issue_comment(动作 created / edited),正文里必须带 @gwei,否则忽略',
    tenant: '引擎写进工作流载荷的顶层 tenant_slug,当前是默认租户 default',
    handoff: '验签 → 去重 → 按租户入队,之后由工作流接管',
  },
]

export function useSignals() {
  // 演示开关在运行时读,不走编译期常量,改环境变量不用重新构建
  const useMock = useRuntimeConfig().public.useMock === true

  const repos = ref<Repo[]>([])
  const plugins = ref<PluginManifestDTO[]>([])
  const loading = ref(true)
  const error = ref<unknown>(null)

  async function fetch() {
    loading.value = true
    error.value = null
    try {
      if (useMock) {
        repos.value = mockSignalRepos
        plugins.value = mockSignalPlugins
      } else {
        const [r, manifests] = await Promise.all([SignalsApi.repos(), SignalsApi.manifests()])
        repos.value = r
        plugins.value = manifests
      }
    } catch (e) {
      error.value = e
    } finally {
      loading.value = false
    }
  }

  /**
   * 按能力名聚合。
   * 同一个能力出现在多个插件下时,把所有提供者都列出来 —— 选谁由引擎的优先级决定,
   * 页面只负责把"这个能力谁会"摊开。
   */
  const capabilities = computed<CapabilityGroup[]>(() => {
    const groups = new Map<string, CapabilityProvider[]>()
    for (const plugin of plugins.value) {
      const declared = plugin.capabilities ?? []
      for (const name of declared) {
        const provider: CapabilityProvider = {
          name: plugin.name,
          version: plugin.version,
          type: plugin.type,
          description: plugin.description,
        }
        const bucket = groups.get(name)
        if (bucket) bucket.push(provider)
        else groups.set(name, [provider])
      }
    }
    return Array.from(groups.entries())
      .map(([name, providers]) => ({ name, providers }))
      .sort((a, b) => a.name.localeCompare(b.name))
  })

  if (import.meta.client) fetch()

  return {
    entries: SIGNAL_ENTRIES,
    repos,
    plugins,
    capabilities,
    loading,
    error,
    refresh: fetch,
  }
}