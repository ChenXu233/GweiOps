import { api } from './typed'
import type { RunList } from '../types/runs'

/**
 * 执行记录:只读投影,没有写接口。
 * limit 走查询串,引擎侧默认 100,这里按控制台习惯拉 200 条。
 */
export const RunsApi = {
  list: (params?: { limit?: number }): Promise<RunList> =>
    api.get('/api/runs', { query: { limit: params?.limit ?? 200 } }),
}
