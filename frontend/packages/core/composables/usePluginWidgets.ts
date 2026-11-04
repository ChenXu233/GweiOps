import { ref } from 'vue'
import { PluginsApi } from '../api/client'
import { mockPluginWidgets } from '../mock'
import type { PluginWidget } from '../types/plugin'

/**
 * 插件 UI 插槽:按槽位拉取插件声明的声明式卡片。
 * 插槽是增强——真实模式拉取失败时静默降级为空,不破坏 dashboard 渲染。
 */
export function usePluginWidgets(slot: string) {
  const useMock = useRuntimeConfig().public.useMock === true
  const widgets = ref<PluginWidget[]>([])

  async function fetch() {
    try {
      if (useMock) {
        widgets.value = mockPluginWidgets.filter(w => w.slot === slot)
      } else {
        widgets.value = await PluginsApi.widgets(slot)
      }
    } catch {
      widgets.value = []
    }
  }

  if (import.meta.client) fetch()

  return { widgets, refresh: fetch }
}
