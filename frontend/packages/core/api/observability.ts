import { api } from './typed'
import type { MetricSample } from '../types/observability'

/**
 * 引擎指标快照:GET /api/metrics
 * 返回引擎收集器里每条时间序列的当前值(最新值去重后的结果)。
 * prefix 可选,交给引擎按指标名前缀过滤。
 */
export const ObservabilityApi = {
  list: (prefix?: string): Promise<MetricSample[]> =>
    api.get('/api/metrics', { query: { prefix } }),
}
