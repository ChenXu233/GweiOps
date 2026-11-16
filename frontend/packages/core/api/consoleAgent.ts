// packages/core/api/consoleAgent.ts
//
// 控制台助手的接口。SSE 与 PATCH 不在 typed.ts 的方法里,故用 fetch;
// 路径与响应体以 ../../../contracts/openapi.json 为准。
import { api } from './typed'

/** 助手可见的一个工具;判据与 MCP 密钥那一栏相同。 */
export interface ConsoleTool {
  name: string
  description: string
  permission: string
  mutating: boolean
}

/** 一次会话:谁在用、权限与白名单、已用改动次数。 */
export interface ConsoleSession {
  id: string
  tenant: string
  actor: string
  permissions: string[]
  bindings: string[]
  tools: string[]
  confirm: boolean
  model: string
  binding: string
  actions: number
  max_actions: number
  created_at: number
  last_used_at: number
  available: ConsoleTool[]
}

export interface ConsolePending {
  id: string
  name: string
  args: Record<string, unknown>
  summary: string
}

export interface ConsoleToolCatalog {
  tools: { name: string; description: string; permission: string; mutating: boolean }[]
  resources: string[]
  default_binding: string
}

export const ConsoleAgentApi = {
  openSession: (body: {
    permissions?: string[]
    bindings?: string[]
    tools?: string[]
    confirm?: boolean
    binding?: string
  }) => api.post('/api/console/session', { body }),

  getSession: (id: string) =>
    api.get('/api/console/session/{session_id}', { path: { session_id: id } }),

  patchSession: async (id: string, body: {
    permissions?: string[]
    bindings?: string[]
    tools?: string[]
    confirm?: boolean
  }): Promise<ConsoleSession> => {
    const res = await fetch(`/api/console/session/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!res.ok) throw new Error(await detailOf(res))
    return (await res.json()) as ConsoleSession
  },

  closeSession: (id: string) =>
    api.delete('/api/console/session/{session_id}', { path: { session_id: id } }),

  pending: (id: string) =>
    api.get('/api/console/session/{session_id}/pending', { path: { session_id: id } }),

  decide: (id: string, callId: string, allow: boolean, reason = '') =>
    api.post('/api/console/session/{session_id}/pending/{call_id}', {
      path: { session_id: id, call_id: callId },
      body: { allow, reason },
    }),

  catalog: () => api.get('/api/console/tools'),
}

async function detailOf(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown }
    if (typeof body.detail === 'string') return body.detail
  } catch {
    // 非 JSON 响应退回状态码
  }
  return `HTTP ${res.status}`
}

/**
 * 发一句话,边收事件边回调。SSE 而非 WebSocket:一问一答,断线重发即可。
 * 返回的 abort 用于停止。
 */
export function streamTurn(
  sessionId: string,
  message: string,
  on: {
    delta?: (text: string) => void
    tool?: (name: string, args: string) => void
    toolResult?: (result: string) => void
    done?: (steps: number) => void
    error?: (message: string) => void
  },
): { abort: () => void; finished: Promise<void> } {
  const controller = new AbortController()
  const finished = (async () => {
    const res = await fetch(
      `/api/console/session/${encodeURIComponent(sessionId)}/turn`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message }),
        signal: controller.signal,
      },
    )
    if (!res.ok || !res.body) {
      on.error?.(await detailOf(res))
      return
    }
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    const dispatch = (chunk: string) => {
      let kind = 'message'
      let data = ''
      for (const line of chunk.split('\n')) {
        if (line.startsWith('event: ')) kind = line.slice(7).trim()
        else if (line.startsWith('data: ')) data += line.slice(6)
      }
      if (!data) return
      let payload: Record<string, unknown> = {}
      try {
        payload = JSON.parse(data) as Record<string, unknown>
      } catch {
        return
      }
      if (kind === 'delta') on.delta?.(String(payload.text ?? ''))
      else if (kind === 'tool') on.tool?.(String(payload.name ?? ''), String(payload.args ?? ''))
      else if (kind === 'tool_result') {
        on.toolResult?.(JSON.stringify(payload.results ?? []))
      } else if (kind === 'error') on.error?.(String(payload.message ?? '事件流缺少 message 字段'))
      else if (kind === 'done') on.done?.(Number(payload.actions ?? 0))
    }
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let cut = buffer.indexOf('\n\n')
      while (cut >= 0) {
        dispatch(buffer.slice(0, cut))
        buffer = buffer.slice(cut + 2)
        cut = buffer.indexOf('\n\n')
      }
    }
    if (buffer.trim()) dispatch(buffer)
  })().catch((e: unknown) => {
    if ((e as Error)?.name !== 'AbortError') on.error?.(String((e as Error)?.message ?? e))
  })

  return { abort: () => controller.abort(), finished }
}
