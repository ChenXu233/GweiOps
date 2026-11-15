import { onMounted, ref } from 'vue'
import { PluginsApi } from '../api/client'
import { mockPluginWidgets } from '../mock'
import type { PluginWidget } from '../types/plugin'

/**
 * 插件 UI 插槽:按槽位拉取插件声明的声明式卡片。
 * 插槽是增强——拉取失败时静默降级为空,不把页面撑成空白。
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

  // 挂载后再拉:首屏与服务端渲染保持一致。演示模式的数据是同步给出的,
  // 在 setup 里直接填会让 hydrate 当场对不上。
  onMounted(() => fetch())

  return { widgets, refresh: fetch }
}