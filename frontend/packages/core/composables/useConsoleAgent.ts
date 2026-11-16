// packages/core/composables/useConsoleAgent.ts
//
// 悬浮窗助手的状态:会话、消息、待批调用。
//
// 权限与计数都由引擎定,这里只做显示与转发:
// - 可用工具(`available`)由引擎按会话权限 + 白名单算出;
// - 改世界的调用待批时 `pending` 非空;
// - 动作计数与上限由引擎给出,不在前端累计。
import { computed, ref } from 'vue'
import {
  ConsoleAgentApi,
  streamTurn,
  type ConsolePending,
  type ConsoleSession,
} from '../api/consoleAgent'

export type MessageRole = 'user' | 'agent' | 'tool' | 'error'

export interface ChatMessage {
  id: number
  role: MessageRole
  text: string
  /** 工具调用:参数与结果分开存,分开显示 */
  tool?: { name: string; args: string; result?: string }
  at: number
}

let seq = 0
function nextId() {
  seq += 1
  return seq
}

export function useConsoleAgent() {
  const useMock = useRuntimeConfig().public.useMock === true
  const session = ref<ConsoleSession | null>(null)
  const messages = ref<ChatMessage[]>([])
  const pending = ref<ConsolePending | null>(null)
  const busy = ref(false)
  const error = ref('')
  const loading = ref(false)
  let running: { abort: () => void } | null = null

  const tools = computed(() => session.value?.available ?? [])
  const mutatingTools = computed(() => tools.value.filter((t) => t.mutating))
  const readonlyTools = computed(() => tools.value.filter((t) => !t.mutating))
  const actionsLeft = computed(() =>
    session.value ? Math.max(0, session.value.max_actions - session.value.actions) : 0,
  )

  function friendly(raw: string): string {
    return raw.replace(/^API error:\s*\d{3}\s*/, '').trim()
  }

  async function ensureSession(): Promise<ConsoleSession | null> {
    if (useMock) return null
    if (session.value) return session.value
    loading.value = true
    try {
      session.value = (await ConsoleAgentApi.openSession({})) as unknown as ConsoleSession
      return session.value
    } catch (e) {
      error.value = friendly(e instanceof Error ? e.message : String(e))
      return null
    } finally {
      loading.value = false
    }
  }

  function say(role: MessageRole, text: string) {
    messages.value.push({ id: nextId(), role, text, at: Date.now() })
  }

  async function send(text: string) {
    const body = text.trim()
    if (!body || busy.value) return
    const current = await ensureSession()
    if (!current) return

    say('user', body)
    busy.value = true
    error.value = ''
    // 先占一条空消息,增量往里填
    const agent: ChatMessage = { id: nextId(), role: 'agent', text: '', at: Date.now() }
    messages.value.push(agent)
    let toolIndex = 0

    const stream = streamTurn(current.id, body, {
      delta: (delta) => {
        agent.text += delta
      },
      tool: (name, args) => {
        const tool = { name, args }
        messages.value.push({ id: nextId(), role: 'tool', text: '', tool, at: Date.now() })
        toolIndex = messages.value.length - 1
      },
      toolResult: (result) => {
        const row = messages.value[toolIndex]
        if (row?.tool) row.tool = { ...row.tool, result }
      },
      error: (message) => {
        error.value = message
        say('error', message)
      },
      done: () => {
        if (!agent.text.trim()) {
          agent.text = '(无输出)'
        }
        void refresh()
      },
    })
    running = stream
    await stream.finished
    running = null
    busy.value = false
    pending.value = null
    await refresh()
  }

  function stop() {
    running?.abort()
    running = null
    busy.value = false
  }

  async function refresh() {
    if (!session.value || useMock) return
    try {
      session.value = (await ConsoleAgentApi.getSession(session.value.id)) as unknown as ConsoleSession
    } catch {
      // 会话已失效,下次发送时重建
      session.value = null
      return
    }
    try {
      const out = (await ConsoleAgentApi.pending(session.value.id)) as unknown as {
        pending: ConsolePending | null
      }
      pending.value = out.pending ?? null
    } catch {
      pending.value = null
    }
  }

  async function decide(allow: boolean, reason = '') {
    const current = session.value
    const call = pending.value
    if (!current || !call) return
    try {
      await ConsoleAgentApi.decide(current.id, call.id, allow, reason)
      pending.value = null
    } catch (e) {
      error.value = friendly(e instanceof Error ? e.message : String(e))
    }
  }

  /** 收窄会话工具白名单;放宽不会超出当前权限,由引擎拒。 */
  async function narrowTools(names: string[]) {
    if (!session.value) return
    try {
      session.value = (await ConsoleAgentApi.patchSession(session.value.id, {
        tools: names,
      })) as ConsoleSession
    } catch (e) {
      error.value = friendly(e instanceof Error ? e.message : String(e))
    }
  }

  async function setConfirm(value: boolean) {
    if (!session.value) return
    try {
      session.value = (await ConsoleAgentApi.patchSession(session.value.id, {
        confirm: value,
      })) as ConsoleSession
    } catch (e) {
      error.value = friendly(e instanceof Error ? e.message : String(e))
    }
  }

  function reset() {
    stop()
    session.value = null
    messages.value = []
    pending.value = null
    error.value = ''
  }

  return {
    useMock,
    session,
    messages,
    pending,
    busy,
    error,
    loading,
    tools,
    mutatingTools,
    readonlyTools,
    actionsLeft,
    ensureSession,
    send,
    stop,
    refresh,
    decide,
    narrowTools,
    setConfirm,
    reset,
    friendly,
  }
}
