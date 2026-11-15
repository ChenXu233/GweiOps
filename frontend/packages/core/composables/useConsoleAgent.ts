// packages/core/composables/useConsoleAgent.ts
//
// 悬浮窗助手的状态：一条会话、一串消息、一张待批的调用。
//
// 三件事都在引擎那边定，这里只负责显示与转发：
// - 能调哪些工具（会话的权限 + 白名单），`available` 就是引擎算出来的清单；
// - 改世界要先有人点允许，`pending` 就是等在门口的那一次；
// - 每次运行的动作数、上限，都由引擎给，不在这里自己数。
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
  /** 工具调用：名字与它跑出来的结果，两者分开显示，人才能看清"它做了什么" */
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
    // 这一轮的回答先占一条空消息，增量往里长
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
          agent.text = '(这一轮没有话要说)'
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
      // 会话过期了：下次说话时重新开一个，不在这里吵
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

  /** 收窄这次对话能给的工具。放宽不会越过这个人手上的权限 —— 引擎会拒。 */
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
