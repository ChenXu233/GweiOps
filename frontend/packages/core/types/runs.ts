// packages/core/types/runs.ts
/**
 * 执行记录:一次 AgentSession 就是一次执行。
 * 字段全部来自 openapi.json 的 RunRowDTO / RunListDTO。
 */
import type { components } from '../api/schema'

type S = components['schemas']

export type RunRow = S['RunRowDTO']
export type RunList = S['RunListDTO']
