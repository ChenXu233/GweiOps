// packages/core/types/signals.ts
/**
 * 信号源页面。webhook 入口与能力聚合都是前端视图模型;
 * 提供者字段直接取自接口里的 PluginDTO,不另抄一份。
 */
import type { PluginManifestDTO } from './plugin'

/** 一个接入口:引擎里真实存在的 webhook 路径。 */
export interface SignalEntry {
  /** 请求路径。挂在引擎根路径下,不带 /api 前缀。 */
  path: string
  /** 目前只有 POST */
  method: 'POST'
  /** 入口的中文名 */
  title: string
  /** 收什么事件 */
  events: string
  /** 租户怎么带 */
  tenant: string
  /** 收下之后交给谁 */
  handoff: string
}

/** 提供某个能力的插件 —— 只保留清单页用得到的字段。 */
export type CapabilityProvider = Pick<
  PluginManifestDTO,
  'name' | 'version' | 'type' | 'description'
>

/**
 * 按能力名聚合的结果。
 * 同一个能力可能出现在多个插件下(适配器之间能力有重叠),
 * 这时把所有提供者都列出来,不做取舍。
 */
export interface CapabilityGroup {
  name: string
  providers: CapabilityProvider[]
}
