// packages/core/types/observability.ts
/**
 * 指标快照。MetricSample 是接口形状(来自 openapi.json),
 * 其余几个是页面算出来的分组模型,不属于接口。
 */
import type { components } from '../api/schema'

type S = components['schemas']

export type MetricSample = S['MetricDTO']

/** 分组后的一行:指标本身 + 它与同组同类上一条序列的比较。 */
export interface MetricRow extends MetricSample {
  /** 稳定 key:指标名 + 标签签名 */
  key: string
  /** 所属分组(指标名的前缀) */
  prefix: string
  /** 同名指标在本组里的条数 */
  familySize: number
  /** 同类里上一条的值;没有上一条则为 null */
  previousValue: number | null
  /** 与上一条的差值;没有上一条则为 null */
  delta: number | null
}

/** 一个前缀分组下的全部序列。 */
export interface MetricGroup {
  /** 指标名的前缀(第一段下划线之前);没有下划线就是整名 */
  prefix: string
  rows: MetricRow[]
  /** 组内不同的指标名个数,即"几类指标" */
  families: number
}
