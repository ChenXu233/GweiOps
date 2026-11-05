<script setup lang="ts">
import { useSignals } from '@gwei/core/composables/useSignals'
import type { SignalEntry } from '@gwei/core/types/signals'
import type { RepoStatus } from '@gwei/core/types/repos'

const { entries, repos, plugins, capabilities, loading, error, refresh } = useSignals()

const statusMeta: Record<RepoStatus, { label: string; cls: string }> = {
  running: { label: '在跑', cls: 'chip-ok' },
  configuring: { label: '配置中', cls: 'chip-warn' },
  paused: { label: '已暂停', cls: '' },
}

// ---------------------------------------------------------------------------
// 能力过滤
// ---------------------------------------------------------------------------
const query = ref('')

const visibleCapabilities = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return capabilities.value
  return capabilities.value.filter(
    (group) =>
      group.name.toLowerCase().includes(q) ||
      group.providers.some((p) => p.name.toLowerCase().includes(q)),
  )
})

// ---------------------------------------------------------------------------
// 复制接入口路径
// ---------------------------------------------------------------------------
type CopyState = 'copied' | 'failed'

const copyState = ref<Record<string, CopyState>>({})
let copyTimer: ReturnType<typeof setTimeout> | null = null

async function writeClipboard(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // 权限不足或非安全上下文:退回到旧接口
  }
  try {
    const holder = document.createElement('textarea')
    holder.value = text
    holder.setAttribute('readonly', '')
    holder.style.position = 'fixed'
    holder.style.opacity = '0'
    document.body.appendChild(holder)
    holder.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(holder)
    return ok
  } catch {
    return false
  }
}

async function copyPath(entry: SignalEntry) {
  const ok = await writeClipboard(entry.path)
  copyState.value = { ...copyState.value, [entry.path]: ok ? 'copied' : 'failed' }
  if (copyTimer) clearTimeout(copyTimer)
  copyTimer = setTimeout(() => {
    const next = { ...copyState.value }
    delete next[entry.path]
    copyState.value = next
  }, 1600)
}

function copyIcon(path: string): string {
  return copyState.value[path] === 'copied' ? 'check' : 'x-circle'
}

function copyLabel(path: string): string {
  const state = copyState.value[path]
  if (state === 'copied') return '已复制'
  if (state === 'failed') return '复制失败'
  return '复制路径'
}

function copyClass(path: string): string {
  const state = copyState.value[path]
  if (state === 'copied') return 'border-ok/40 text-ok'
  if (state === 'failed') return 'border-coral/40 text-coral'
  return ''
}

onUnmounted(() => {
  if (copyTimer) clearTimeout(copyTimer)
})

// ---------------------------------------------------------------------------
// 时间
// ---------------------------------------------------------------------------
function formatSync(value: string): string {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      eyebrow="SIGNALS"
      title="信号源"
      description="外部世界的动静是从哪儿进来的:webhook 收信,仓库订阅限定范围,插件提供回应的能力。"
    >
      <template #actions>
        <button class="btn-outline btn-sm" :disabled="loading" @click="refresh()">
          <AppIcon name="refresh" :size="13" :class="loading ? 'animate-spin' : ''" />
          {{ loading ? '刷新中…' : '刷新' }}
        </button>
      </template>
    </PageHeader>

    <div
      v-if="error"
      class="rounded-panel border border-coral/30 bg-coral/5 p-4 text-[12.5px] text-coral"
    >
      拉不到接入口数据。确认引擎在跑,或开启 mock 模式。
    </div>

    <!-- 一眼看完的四个数 -->
    <div class="panel-inset flex flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3.5">
      <div>
        <div class="mono-label">接入口</div>
        <div class="num mt-1 text-[16px] font-semibold">{{ entries.length }}</div>
      </div>
      <span class="hidden h-8 w-px bg-line sm:block" />
      <div>
        <div class="mono-label">订阅仓库</div>
        <div class="num mt-1 text-[16px] font-semibold">{{ repos.length }}</div>
      </div>
      <span class="hidden h-8 w-px bg-line sm:block" />
      <div>
        <div class="mono-label">插件</div>
        <div class="num mt-1 text-[16px] font-semibold">{{ plugins.length }}</div>
      </div>
      <span class="hidden h-8 w-px bg-line sm:block" />
      <div>
        <div class="mono-label">可用能力</div>
        <div class="num mt-1 text-[16px] font-semibold">{{ capabilities.length }}</div>
      </div>
    </div>

    <!-- 第一块:接入口 -->
    <section class="space-y-3">
      <div class="flex flex-wrap items-baseline justify-between gap-2">
        <h2 class="text-[15px] font-semibold">接入口</h2>
        <span class="mono-label">WEBHOOK</span>
      </div>

      <p class="max-w-[72ch] text-[12.5px] leading-relaxed text-ink-soft">
        GitHub 把动静送到下面这两个路径。两个入口都校验
        <span class="font-mono text-[11.5px]">X-Hub-Signature-256</span>,
        密钥在 GitHub 与引擎两侧各配一份,不经过这个页面。
      </p>

      <div class="grid gap-4 md:grid-cols-2">
        <article
          v-for="entry in entries"
          :key="entry.path"
          class="panel panel-lift flex flex-col p-5"
        >
          <div class="flex items-start justify-between gap-3">
            <span class="grid h-9 w-9 place-items-center rounded-tile bg-well text-ink-soft">
              <AppIcon name="webhook" :size="16" />
            </span>
            <span class="chip chip-info">{{ entry.method }}</span>
          </div>

          <h3 class="mt-4 text-[13.5px] font-semibold">{{ entry.title }}</h3>

          <div class="mt-2.5 flex items-center gap-2 rounded-tile border border-line bg-well/60 px-3 py-2">
            <code class="min-w-0 flex-1 break-all font-mono text-[12px] text-ink">{{ entry.path }}</code>
            <button
              class="btn-outline btn-sm min-w-[76px] shrink-0"
              :class="copyClass(entry.path)"
              @click="copyPath(entry)"
            >
              <AppIcon v-if="copyState[entry.path]" :name="copyIcon(entry.path)" :size="13" />
              {{ copyLabel(entry.path) }}
            </button>
          </div>

          <dl class="mt-4 space-y-3 border-t border-line/70 pt-3.5">
            <div>
              <dt class="mono-label">收什么事件</dt>
              <dd class="mt-1 text-[12px] leading-relaxed text-ink-soft">{{ entry.events }}</dd>
            </div>
            <div>
              <dt class="mono-label">租户怎么带</dt>
              <dd class="mt-1 text-[12px] leading-relaxed text-ink-soft">{{ entry.tenant }}</dd>
            </div>
            <div>
              <dt class="mono-label">收下之后</dt>
              <dd class="mt-1 text-[12px] leading-relaxed text-ink-soft">{{ entry.handoff }}</dd>
            </div>
          </dl>
        </article>
      </div>

      <div class="panel-inset flex items-start gap-3 px-4 py-3.5">
        <AppIcon name="workflow" :size="15" class="mt-0.5 shrink-0 text-ink-faint" />
        <p class="text-[12px] leading-relaxed text-ink-soft">
          <span class="font-medium text-ink">信号进来之后由工作流接管。</span>
          webhook 只负责验签、去重、按租户入队;诊断、方案生成、验证与回评都在工作流里,
          具体用哪个能力由插件决定。
        </p>
      </div>
    </section>

    <!-- 第二块:仓库订阅 -->
    <section class="space-y-3">
      <div class="flex flex-wrap items-baseline justify-between gap-2">
        <h2 class="text-[15px] font-semibold">仓库订阅</h2>
        <span class="mono-label">REPOSITORIES</span>
      </div>

      <div v-if="loading && !repos.length" class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <div v-for="i in 3" :key="i" class="skeleton h-[168px] rounded-panel" />
      </div>

      <div v-else-if="!repos.length" class="panel">
        <EmptyState
          icon="repos"
          title="还没有订阅仓库"
          hint="在 GitHub 侧把 webhook 指向上面的接入口,并把仓库绑到当前租户;引擎认领之后,订阅关系会出现在这里。"
        />
      </div>

      <div v-else class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <article
          v-for="repo in repos"
          :key="repo.id"
          class="panel panel-lift flex flex-col p-5"
        >
          <div class="flex items-start justify-between gap-3">
            <span class="grid h-9 w-9 place-items-center rounded-tile bg-well text-ink-soft">
              <AppIcon name="repos" :size="16" />
            </span>
            <span class="chip" :class="statusMeta[repo.status].cls">
              {{ statusMeta[repo.status].label }}
            </span>
          </div>

          <h3 class="mt-4 break-all font-mono text-[13px] font-medium leading-snug">{{ repo.name }}</h3>

          <div class="mt-auto grid grid-cols-2 gap-3 border-t border-line/70 pt-3.5">
            <div>
              <div class="mono-label">议题</div>
              <div class="num mt-1 text-[15px] font-semibold">{{ repo.issueCount }}</div>
            </div>
            <div>
              <div class="mono-label">最后同步</div>
              <div class="num mt-1 text-[12.5px] text-ink-soft">{{ formatSync(repo.lastSyncAt) }}</div>
            </div>
          </div>
        </article>
      </div>
    </section>

    <!-- 第三块:能响应的能力 -->
    <section class="space-y-3">
      <div class="flex flex-wrap items-baseline justify-between gap-2">
        <h2 class="text-[15px] font-semibold">能响应的能力</h2>
        <span class="mono-label">CAPABILITIES</span>
      </div>

      <p class="max-w-[72ch] text-[12.5px] leading-relaxed text-ink-soft">
        能力由插件提供,引擎只编排。同一个能力出现在多个插件下时,这里把提供者都列出来,
        最终选谁由引擎按优先级决定。
      </p>

      <div class="flex flex-wrap items-center gap-3">
        <div class="relative w-full sm:max-w-[280px]">
          <AppIcon
            name="search"
            :size="14"
            class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint"
          />
          <input
            v-model="query"
            type="search"
            class="field pl-9"
            placeholder="按能力或插件过滤"
            aria-label="按能力或插件过滤"
          />
        </div>
        <span class="mono-label">
          <span class="num">{{ visibleCapabilities.length }}</span> / {{ capabilities.length }} 项能力
        </span>
      </div>

      <div v-if="loading && !capabilities.length" class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <div v-for="i in 6" :key="i" class="skeleton h-[112px] rounded-panel" />
      </div>

      <div v-else-if="!capabilities.length" class="panel">
        <EmptyState
          icon="plugins"
          title="还没有插件声明能力"
          hint="把带 manifest 的插件放进 plugins/ 目录,引擎启动时发现它们,能力就会出现在这里。"
        />
      </div>

      <div v-else-if="!visibleCapabilities.length" class="panel">
        <EmptyState
          icon="search"
          title="没有匹配的能力"
          hint="换个关键词,或者清空过滤条件,看看全部能力。"
        />
      </div>

      <div v-else class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <article
          v-for="group in visibleCapabilities"
          :key="group.name"
          class="panel flex flex-col p-4"
        >
          <div class="flex items-start justify-between gap-2">
            <span class="min-w-0 break-all font-mono text-[12.5px] font-medium">{{ group.name }}</span>
            <span class="chip shrink-0">
              <span class="num font-mono">{{ group.providers.length }}</span> 个插件
            </span>
          </div>

          <ul class="mt-3 space-y-2">
            <li
              v-for="provider in group.providers"
              :key="provider.name"
              class="flex items-center gap-2 text-[12px] text-ink-soft"
            >
              <span class="dot bg-ink-faint" />
              <span class="min-w-0 truncate">{{ provider.name }}</span>
              <span class="mono-label ml-auto shrink-0">{{ provider.type }}</span>
            </li>
          </ul>
        </article>
      </div>
    </section>
  </div>
</template>
