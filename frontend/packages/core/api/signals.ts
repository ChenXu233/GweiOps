import { api } from './typed'
import type { PluginManifestDTO } from '../types/plugin'
import type { Repo } from '../types/repos'

/**
 * 信号源用到的只读接口。
 *
 * 对应引擎真实存在的两个端点:
 * - GET /api/repos    控制台只读投影(engine/api/routes/console.py)
 * - GET /api/plugins  插件注册表清单(engine/api/routes/plugins.py)
 *
 * 入站 webhook 不在这里:它由 GitHub 投递,不走控制台。
 */
export const SignalsApi = {
  repos: (): Promise<Repo[]> => api.get('/api/repos'),
  manifests: (): Promise<PluginManifestDTO[]> => api.get('/api/plugins'),
}
