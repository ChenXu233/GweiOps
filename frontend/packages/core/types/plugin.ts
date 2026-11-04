// 插件声明式 UI 与清单的类型(engine /api/plugins 返回的形状)

export type PluginWidgetVariant = 'default' | 'green' | 'yellow' | 'red'

export interface PluginWidgetMetric {
  label: string
  value: string | number
  sub?: string
  variant?: PluginWidgetVariant
}

export interface PluginWidgetItem {
  text: string
}

/** 插件经 manifest 声明的 UI 卡片(声明式 schema,核心渲染) */
export interface PluginWidget {
  plugin: string
  slot: string
  kind: 'metric' | 'list'
  span: number
  title: string
  metrics?: PluginWidgetMetric[]
  items?: PluginWidgetItem[]
}

/** 引擎返回的原始 widget 就是上面这个形状 */
export type PluginWidgetDTO = PluginWidget

export interface PluginManifestDTO {
  name: string
  version: string
  type: string
  description: string
  capabilities: string[]
  widgets: PluginWidget[]
  pages: { title?: string; entry?: string }[]
}
