// packages/core/types/plugin.ts
// 插件清单与声明式 UI 卡片。形状来自 openapi.json。
import type { components } from '../api/schema'

type S = components['schemas']

export type PluginWidgetMetric = S['PluginWidgetMetricDTO']
export type PluginWidgetItem = S['PluginWidgetItemDTO']

/** 插件经 manifest 声明的一张卡片(声明式 schema,由核心渲染) */
export type PluginWidget = S['PluginWidgetDTO']
export type PluginWidgetDTO = PluginWidget

/** 引擎原始清单(含 capabilities / widgets / pages 声明) */
export type PluginManifestDTO = S['PluginDTO']

export type PluginWidgetVariant = NonNullable<PluginWidgetMetric['variant']>
