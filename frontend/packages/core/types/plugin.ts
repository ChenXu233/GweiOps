// engine /api/plugins 的原始 DTO(manifest 声明的镜像)

export interface PluginWidgetMetricDTO {
  label: string
  value: string | number
  sub?: string
  variant?: string
}

export interface PluginWidgetItemDTO {
  text: string
}

export interface PluginWidgetDTO {
  plugin: string
  slot: string
  kind: 'metric' | 'list'
  span: number
  title: string
  metrics?: PluginWidgetMetricDTO[]
  items?: PluginWidgetItemDTO[]
}

export interface PluginManifestDTO {
  name: string
  version: string
  type: string
  description: string
  capabilities: string[]
  widgets: PluginWidgetDTO[]
  pages: Record<string, unknown>[]
}
