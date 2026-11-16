<script setup lang="ts">
// 控制台助手:右下角悬浮窗。
//
// 从上到下:工具与权限面板、对话、批准卡、输入。
// 权限判定都在引擎侧,前端只展示:
// - 可用工具来自引擎的 `available`,前端不自行筛选;
// - 改世界的调用待批时才出现批准卡,决定后才执行。
import { useConsoleAgent } from '@gwei/core/composables/useConsoleAgent'

const agent = useConsoleAgent()
const open = ref(false)
const draft = ref('')
const showTools = ref(false)
const scroller = ref<HTMLElement | null>(null)

const { can } = useAuth()
// 看得到账本就能跟它说话；改世界的动作另外由会话里的权限与批准管
const allowed = computed(() => can('changes.read'))

const placeholder = computed(() =>
  agent.actionsLeft.value > 0 ? '输入消息…' : '本次对话改动次数已用完,请重新开始会话',
)

async function submit() {
  const text = draft.value.trim()
  if (!text) return
  draft.value = ''
  await agent.send(text)
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    void submit()
  }
}

async function toggle() {
  open.value = !open.value
  if (open.value && !agent.session.value) {
    await agent.ensureSession()
  }
}

function toggleTool(name: string) {
  const current = new Set(agent.session.value?.tools ?? [])
  if (current.size === 0) {
    // 空 = 不限;首次取消勾选时把全部工具落成名单
    for (const tool of agent.tools.value) current.add(tool.name)
  }
  if (current.has(name)) current.delete(name)
  else current.add(name)
  void agent.narrowTools([...current])
}

function toolChecked(name: string) {
  const narrowed = agent.session.value?.tools ?? []
  return narrowed.length === 0 || narrowed.includes(name)
}

function when(at: number) {
  return new Date(at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

function prettyArgs(raw: string): string {
  try {
    const parsed = JSON.parse(raw || '{}') as Record<string, unknown>
    const clean = Object.fromEntries(
      Object.entries(parsed).filter(([key]) => !key.startsWith('_')),
    )
    return JSON.stringify(clean, null, 2)
  } catch {
    return raw
  }
}

// 新消息进来时滚动到底部
watch(
  () => agent.messages.value.length,
  async () => {
    await nextTick()
    if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight
  },
)

const dockLabel = computed(() => (open.value ? '收起助手' : '打开助手'))
</script>

<template>
  <div class="fixed bottom-5 right-5 z-40 flex flex-col items-end gap-3">
    <!-- 窗口 -->
    <Transition
      enter-active-class="transition duration-200 ease-out"
      enter-from-class="translate-y-2 scale-[0.98] opacity-0"
      leave-active-class="transition duration-150 ease-in"
      leave-to-class="translate-y-2 scale-[0.98] opacity-0"
    >
      <section
        v-if="open"
        class="panel flex h-[min(70vh,560px)] w-[min(92vw,392px)] flex-col overflow-hidden shadow-2xl"
      >
        <header class="flex items-center gap-2 border-b border-line px-4 py-3">
          <AppIcon name="sparkles" :size="14" class="text-ink-faint" />
          <span class="text-[13px] font-medium">控制台助手</span>
          <span class="chip ml-1">
            <span class="dot" :class="agent.busy.value ? 'bg-amber' : 'bg-ok'" />
            {{ agent.busy.value ? '运行中' : '空闲' }}
          </span>
          <button
            class="btn-ghost ml-auto h-7 px-2 text-[11.5px]"
            :class="showTools ? 'text-ink' : 'text-ink-faint'"
            title="工具与权限"
            @click="showTools = !showTools"
          >
            <AppIcon name="list-checks" :size="13" />
          </button>
          <button class="btn-icon h-7 w-7" aria-label="收起" @click="open = false">
            <AppIcon name="x" :size="14" />
          </button>
        </header>

        <!-- 权限面板：谁、剩几次、要不要人点 -->
        <div v-if="showTools" class="max-h-[45%] overflow-y-auto border-b border-line bg-well/50 px-4 py-3">
          <div class="flex flex-wrap items-center gap-1.5">
            <span class="mono-label">本次对话</span>
            <span class="chip">{{ agent.session.value?.actor || '未登录' }}</span>
            <span class="chip">剩 {{ agent.actionsLeft.value }} 次改动</span>
          </div>
          <label class="mt-2 flex items-center gap-2 text-[11.5px] text-ink-soft">
            <input
              type="checkbox"
              :checked="agent.session.value?.confirm ?? true"
              :disabled="!agent.session.value || agent.busy.value"
              @change="agent.setConfirm(($event.target as HTMLInputElement).checked)"
            >
            改世界前需确认(关闭后直接执行,仍会记账)
          </label>

          <div class="mt-2.5 space-y-1.5">
            <div v-if="agent.mutatingTools.value.length">
              <span class="mono-label">改世界</span>
              <div class="mt-1 flex flex-wrap gap-1">
                <button
                  v-for="t in agent.mutatingTools.value"
                  :key="t.name"
                  class="chip font-mono text-[10.5px] transition-colors"
                  :class="toolChecked(t.name) ? 'border-ink/30 bg-ink text-paper' : 'opacity-50'"
                  :disabled="agent.busy.value"
                  :title="`${t.description} · 需要 ${t.permission}`"
                  @click="toggleTool(t.name)"
                >
                  {{ t.name }}
                </button>
              </div>
            </div>
            <div v-if="agent.readonlyTools.value.length">
              <span class="mono-label">只看</span>
              <div class="mt-1 flex flex-wrap gap-1">
                <button
                  v-for="t in agent.readonlyTools.value"
                  :key="t.name"
                  class="chip font-mono text-[10.5px] transition-colors"
                  :class="toolChecked(t.name) ? 'border-ink/30 bg-ink text-paper' : 'opacity-50'"
                  :disabled="agent.busy.value"
                  :title="t.description"
                  @click="toggleTool(t.name)"
                >
                  {{ t.name }}
                </button>
              </div>
            </div>
            <p v-if="!agent.tools.value.length" class="text-[11.5px] text-ink-faint">
              当前身份没有可用工具。
            </p>
            <p class="text-[10.5px] leading-relaxed text-ink-faint">
              取消勾选即收窄工具;收窄无需批准,放宽不会超出当前权限。
            </p>
          </div>
        </div>

        <!-- 对话 -->
        <div ref="scroller" class="flex-1 space-y-3 overflow-y-auto px-4 py-3">
          <div v-if="agent.useMock" class="panel-inset px-3 py-2 text-[11.5px] text-ink-soft">
            演示模式未连接引擎,工具不可用。
          </div>

          <div v-else-if="!allowed" class="panel-inset px-3 py-2 text-[11.5px] text-ink-soft">
            缺少 <code class="font-mono text-[11px]">changes.read</code> 权限,无法使用。
          </div>

          <template v-else>
            <div
              v-if="!agent.messages.value.length"
              class="space-y-2 text-[12px] leading-relaxed text-ink-soft"
            >
              <p>可查询账本、议题与插件,也可执行需要授权的操作。</p>
              <p class="text-[11.5px] text-ink-faint">
                改世界的动作需批准后执行,执行仍过闸门并记账。
              </p>
            </div>

            <div
              v-for="m in agent.messages.value"
              :key="m.id"
              class="space-y-1"
            >
              <div v-if="m.role === 'user'" class="flex justify-end">
                <div class="max-w-[85%] rounded-card bg-ink px-3 py-2 text-[12.5px] leading-relaxed text-paper">
                  {{ m.text }}
                </div>
              </div>

              <div v-else-if="m.role === 'agent'" class="max-w-[92%] text-[12.5px] leading-relaxed">
                <span class="whitespace-pre-wrap">{{ m.text }}</span>
                <span v-if="agent.busy.value && !m.text" class="text-ink-faint">生成中…</span>
              </div>

              <div v-else-if="m.role === 'error'" class="rounded-card border border-coral/30 bg-coral/5 px-3 py-2 text-[11.5px] text-coral">
                {{ m.text }}
              </div>

              <details v-else class="rounded-card border border-line bg-well/60 px-2.5 py-2">
                <summary class="flex cursor-pointer items-center gap-1.5 text-[11.5px]">
                  <AppIcon name="terminal" :size="12" class="text-ink-faint" />
                  <span class="font-mono">{{ m.tool?.name }}</span>
                  <span v-if="m.tool?.result" class="chip ml-auto text-[10px]">已完成</span>
                  <span v-else class="chip chip-warn ml-auto text-[10px]">进行中</span>
                </summary>
                <pre class="mt-1.5 overflow-x-auto font-mono text-[10.5px] leading-relaxed text-ink-soft">{{ prettyArgs(m.tool?.args || '') }}</pre>
                <pre v-if="m.tool?.result" class="mt-1 overflow-x-auto border-t border-line/60 pt-1.5 font-mono text-[10.5px] leading-relaxed text-ink-faint">{{ m.tool.result }}</pre>
              </details>

              <span class="mono-label block">{{ when(m.at) }}</span>
            </div>
          </template>
        </div>

        <!-- 批准卡：这一件事在等人点 -->
        <div
          v-if="agent.pending.value"
          class="border-t border-amber/40 bg-amber/5 px-4 py-3"
        >
          <div class="flex items-center gap-1.5 text-[12px] font-medium">
            <AppIcon name="shield-alert" :size="13" class="text-amber" />
            改世界的调用待批准
          </div>
          <div class="mt-1 font-mono text-[11.5px]">{{ agent.pending.value.name }}</div>
          <pre class="mt-1 max-h-24 overflow-auto rounded-card border border-line bg-well px-2 py-1.5 font-mono text-[10.5px] leading-relaxed text-ink-soft">{{ prettyArgs(JSON.stringify(agent.pending.value.args)) }}</pre>
          <div class="mt-2 flex items-center gap-2">
            <button class="btn-solid h-7 px-2.5 text-[11.5px]" @click="agent.decide(true)">
              允许并执行
            </button>
            <button class="btn-outline h-7 px-2.5 text-[11.5px]" @click="agent.decide(false)">
              不允许
            </button>
            <span class="text-[10.5px] text-ink-faint">批准后仍需通过出口判定</span>
          </div>
        </div>

        <!-- 输入 -->
        <footer class="border-t border-line px-3 py-2.5">
          <p v-if="agent.error.value" class="mb-1.5 text-[11px] text-coral">{{ agent.error.value }}</p>
          <textarea
            v-model="draft"
            :placeholder="allowed ? placeholder : '无使用权限'"
            :disabled="!allowed || agent.busy.value"
            rows="2"
            class="w-full resize-none rounded-card border border-line bg-well px-2.5 py-2 text-[12.5px] leading-relaxed outline-none focus:border-line-strong disabled:opacity-60"
            @keydown="onKey"
          />
          <div class="mt-1.5 flex items-center gap-2">
            <span class="mono-label">{{ agent.session.value?.binding || '' }}</span>
            <button
              v-if="agent.busy.value"
              class="btn-outline ml-auto h-7 px-2.5 text-[11.5px]"
              @click="agent.stop()"
            >
              停
            </button>
            <button
              v-else
              class="btn-solid ml-auto h-7 px-3 text-[11.5px]"
              :disabled="!allowed || !draft.trim()"
              @click="submit"
            >
              说
            </button>
          </div>
        </footer>
      </section>
    </Transition>

    <!-- 把手 -->
    <button
      class="relative grid h-12 w-12 place-items-center rounded-full border border-line bg-paper text-ink shadow-lg transition-transform hover:scale-105"
      :title="dockLabel"
      :aria-label="dockLabel"
      @click="toggle"
    >
      <AppIcon v-if="!open" name="sparkles" :size="19" />
      <AppIcon v-else name="chevron-down" :size="19" />
      <span
        v-if="agent.pending.value && !open"
        class="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full bg-amber"
      />
    </button>
  </div>
</template>
