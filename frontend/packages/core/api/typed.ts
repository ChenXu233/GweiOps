// packages/core/api/typed.ts
//
// 同源调用 + 类型来自 ../../../contracts/openapi.json(经 pnpm gen:api 生成)。
// 加接口不再手抄字段:路径、路径参数、响应体都由 schema 推出来。
//
//   const issues = await api.get('/api/issues')                 // IssueDTO[]
//   const one    = await api.get('/api/issues/{issue_id}', { path: { issue_id: id } })
//   const blocked= await api.get('/api/changes', { query: { verdict: 'blocked' } })
//   await api.post('/api/changes/{unit_id}/approve', { path: { unit_id: id } })
//
import type { paths } from './schema'

type Paths = paths
type Method = 'get' | 'post'

/** 哪些路径支持某个方法。 */
type RoutesWith<M extends Method> = {
  [P in keyof Paths]: Paths[P] extends Record<M, unknown> ? P : never
}[keyof Paths]

type JsonBody<Op> = Op extends { responses: { 200: { content: { 'application/json': infer B } } } }
  ? B
  : never

/** 某个 路径 × 方法 的 200 响应体类型。 */
export type ResponseOf<P extends RoutesWith<M>, M extends Method> = Paths[P] extends Record<
  M,
  infer Op
>
  ? JsonBody<Op>
  : never

type PathParams<P extends string> = P extends `${string}{${infer Name}}${infer Rest}`
  ? { [K in Name | keyof PathParams<`{${Rest}`>]: string | number }
  : never

export interface CallOptions<P extends string> {
  /** 填 {name} 占位符;名字拼错在编译期就会报错 */
  path?: [PathParams<P>] extends [never] ? never : PathParams<P>
  query?: Record<string, string | number | boolean | undefined | null>
  signal?: AbortSignal
}

export interface PostOptions<P extends string> extends CallOptions<P> {
  body?: unknown
}

const BASE = ''

function fillPath(template: string, params?: Record<string, string | number>): string {
  if (!params) return template
  return template.replace(/\{(\w+)\}/g, (_, key: string) => {
    const value = params[key]
    if (value === undefined) throw new Error(`missing path param: ${key}`)
    return encodeURIComponent(String(value))
  })
}

function withQuery(url: string, query?: CallOptions<string>['query']): string {
  if (!query) return url
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null) continue
    search.set(key, String(value))
  }
  const qs = search.toString()
  return qs ? `${url}?${qs}` : url
}

/** 与旧 apiClient 完全一致的错误形状:上层用 /API error: (\d{3})/ 取状态码。 */
async function send<T>(url: string, init: RequestInit): Promise<T> {
  const res = await fetch(BASE + url, init)
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export const api = {
  get<P extends RoutesWith<'get'>>(path: P, options?: CallOptions<P>): Promise<ResponseOf<P, 'get'>> {
    const url = withQuery(fillPath(path, options?.path as never), options?.query)
    return send<ResponseOf<P, 'get'>>(url, { method: 'GET', signal: options?.signal })
  },

  post<P extends RoutesWith<'post'>>(
    path: P,
    options?: PostOptions<P>,
  ): Promise<ResponseOf<P, 'post'>> {
    const url = withQuery(fillPath(path, options?.path as never), options?.query)
    return send<ResponseOf<P, 'post'>>(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: options?.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options?.signal,
    })
  },
}
