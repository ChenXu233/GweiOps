<script setup lang="ts">
// MCP 接入 —— 给外界的 agent 签一把钥匙,并看清楚它拿到什么。
//
// 三块从上到下按人做这件事的顺序:地址与请求头(贴进客户端)、签一把(勾资源与
// 权限)、清单(谁签过、够得着什么、停不停)。权限、资源、工具三份清单一律来自
// 引擎,这里不自己编 —— 页面显示的就是 tools/list 会给对方的。
import {
  useMcpKeys,
  visibleTools,
  type McpKey,
  type McpKeyDraft,
} from '@gwei/core/composables/useMcpKeys'

const { can } = useAuth()
const {
  useMock,
  resources,
  tools,
  permissions,
  activeKeys,
  revokedKeys,
  loading,
  error,
  load,
  issue,
  revoke,
  permissionLabel,
  friendly,
} = useMcpKeys()

const canRead = computed(() => can('keys.read'))
const canManage = computed(() => can('keys.manage'))

const draft = reactive<McpKeyDraft>({
  name: '',
  permissions: [],
  bindings: [],
  tools: [],
  expires_at: '',
})

// 签出来的明文只在这一处出现一次:关掉这块就再也拿不到
const fresh = ref<{ name: string, key: string } | null>(null)
const issuing = ref(false)
const revoking = ref<string | null>(null)
const formError = ref('')

const preview = computed(() => visibleTools(tools.value, draft))

function toggle(list: string[], value: string) {
  const i = list.indexOf(value)
  if (i >= 0) list.splice(i, 1)
  else list.push(value)
}

/** 选了资源之后,只留下那些资源上真有的工具 —— 不然白名单会悄悄砍掉清单。 */
function toolsOnSelectedResources() {
  if (!draft.bindings.length) return tools.value
  return tools.value.filter(
    (t) => !t.resources.length || t.resources.some((r) => draft.bindings.includes(r)),
  )
}

// 会改世界的与只读的分开放:前者过闸门、落账,后者看一眼就走,不是一回事。
const mutatingTools = computed(() => toolsOnSelectedResources().filter((t) => t.mutating))
const readonlyTools = computed(() => toolsOnSelectedResources().filter((t) => !t.mutating))

async function submit() {
  formError.value = ''
  issuing.value = true
  try {
    const issued = await issue(draft)
    fresh.value = { name: issued.name, key: issued.key ?? '' }
    // 只清名字:接着签第二把常常是同一套权限换一个客户端,重勾一遍纯属浪费
    draft.name = ''
  } catch (e) {
    formError.value = friendly(e instanceof Error ? e.message : String(e))
  } finally {
    issuing.value = false
  }
}

async function onRevoke(key: McpKey) {
  if (!window.confirm(`吊销「${key.name || key.hint}」?之后它的每个请求都是 401,记录留着。`)) return
  revoking.value = key.id
  try {
    await revoke(key.id)
  } catch (e) {
    formError.value = friendly(e instanceof Error ? e.message : String(e))
  } finally {
    revoking.value = null
  }
}

// 接入地址:同一个站点,补上 /mcp。复制给自己贴进客户端。
const mcpUrl = computed(() => {
  if (!import.meta.client) return '/mcp'
  return `${window.location.origin}/mcp`
})

const copied = ref('')
async function copy(text: string, what: string) {
  try {
    await navigator.clipboard.writeText(text)
    copied.value = what
    setTimeout(() => {
      if (copied.value === what) copied.value = ''
    }, 2000)
  } catch {
    // 剪贴板不可用(非 https / 拒绝授权):值就在页面上,手动选中即可
  }
}

function when(iso: string) {
  if (!iso) return ''
  return iso.slice(0, 16).replace('T', ' ')
}

onMounted(load)
</script>

<template>
  <div class="space-y-5">
    <PageHeader
      eyebrow="AGENT ACCESS"
      title="MCP 接入"
      description="外界的 agent 用一把密钥接上这台机器。密钥有什么权限、能碰哪些资源,它看到的工具就是哪些。"
    >
      <template #actions>
        <button class="btn-outline btn-sm" :disabled="loading" @click="load">
          <AppIcon name="refresh" :size="13" :class="loading ? 'animate-spin' : ''" />
          刷新
        </button>
      </template>
    </PageHeader>

    <div v-if="useMock" class="panel border-amber/30 bg-amber/5 p-4 text-[12.5px] text-ink-soft">
      演示模式没有引擎,也就没有可签的凭据。接上真实引擎后这一页就是签发与吊销的地方。
    </div>

    <div
      v-else-if="!canRead"
      class="panel border-line p-4 text-[12.5px] text-ink-soft"
    >
      你手上没有 <code class="font-mono text-[11.5px]">keys.read</code>,看不到这台机器的密钥。
      找所有者要一条,或者让他替你签。
    </div>

    <template v-else>
      <div v-if="error" class="panel border-coral/30 bg-coral/5 p-4 text-[12.5px] text-coral">
        {{ error }}
      </div>

      <!-- 一、贴进客户端的两样东西 -->
      <section class="panel overflow-hidden">
        <div class="flex items-center gap-2 border-b border-line px-5 py-3.5">
          <AppIcon name="plug" :size="14" class="text-ink-faint" />
          <h2 class="text-[13px] font-semibold">客户端填什么</h2>
          <span class="eyebrow ml-auto">ENDPOINT</span>
        </div>

        <div class="px-5 py-4">
          <p class="text-[12.5px] leading-relaxed text-ink-soft">
            支持 MCP 的客户端(Claude Code、Cursor、dsh)都填这两样:一个流式 HTTP 地址,
            一个把密钥放进去的请求头。工具清单由引擎按这把密钥算,不用你手抄。
          </p>

          <div class="mt-3 grid gap-2 sm:grid-cols-2">
            <div class="panel-inset px-3 py-2">
              <span class="block text-[11px] text-ink-faint">地址(streamable HTTP)</span>
              <div class="mt-0.5 flex items-center gap-2">
                <code class="min-w-0 flex-1 truncate font-mono text-[12px]">{{ mcpUrl }}</code>
                <button class="btn-ghost h-6 px-1.5 text-[11px]" @click="copy(mcpUrl, 'url')">
                  {{ copied === 'url' ? '已复制' : '复制' }}
                </button>
              </div>
            </div>
            <div class="panel-inset px-3 py-2">
              <span class="block text-[11px] text-ink-faint">凭据请求头</span>
              <code class="mt-0.5 block truncate font-mono text-[12px]">
                X-Gwei-Token: &lt;密钥&gt;
              </code>
            </div>
          </div>

          <details class="mt-3 group">
            <summary class="cursor-pointer text-[11.5px] text-ink-faint hover:text-ink-soft">
              客户端配置长什么样
            </summary>
            <pre class="mt-2 overflow-x-auto rounded-card border border-line bg-well px-3 py-2.5 font-mono text-[11px] leading-relaxed text-ink-soft">{
  "mcpServers": {
    "gweiops": {
      "type": "http",
      "url": "{{ mcpUrl }}",
      "headers": { "X-Gwei-Token": "gwei_..." }
    }
  }
}</pre>
          </details>
        </div>
      </section>

      <!-- 二、签一把 -->
      <section v-if="canManage" class="panel overflow-hidden">
        <div class="flex items-center gap-2 border-b border-line px-5 py-3.5">
          <AppIcon name="key-round" :size="14" class="text-ink-faint" />
          <h2 class="text-[13px] font-semibold">签一把密钥</h2>
          <span class="eyebrow ml-auto">ISSUE</span>
        </div>

        <div class="space-y-4 px-5 py-4">
          <div class="grid gap-3 sm:grid-cols-2">
            <label class="block">
              <span class="mb-1 block text-[11.5px] text-ink-soft">
                这把密钥给谁用 <span class="text-coral">*</span>
              </span>
              <input
                v-model="draft.name"
                placeholder="例:claude-code 本机"
                class="w-full rounded-card border border-line bg-well px-3 py-2 text-[12.5px] outline-none focus:border-line-strong"
                autocomplete="off"
              >
            </label>
            <label class="block">
              <span class="mb-1 block text-[11.5px] text-ink-soft">
                到期时间 <span class="text-ink-faint">(留空 = 不过期)</span>
              </span>
              <input
                v-model="draft.expires_at"
                type="datetime-local"
                class="w-full rounded-card border border-line bg-well px-3 py-2 text-[12.5px] outline-none focus:border-line-strong"
              >
            </label>
          </div>

          <!-- 资源:这把钥匙能碰哪些下游目标 -->
          <div>
            <div class="mb-1.5 flex items-center gap-2">
              <span class="text-[11.5px] text-ink-soft">能碰哪些资源</span>
              <span class="text-[11px] text-ink-faint">不勾 = 不限</span>
            </div>
            <div v-if="resources.length" class="grid gap-2 sm:grid-cols-2">
              <button
                v-for="r in resources"
                :key="r.key"
                type="button"
                class="rounded-card border px-3 py-2 text-left transition-colors"
                :class="draft.bindings.includes(r.key) ? 'border-ink/30 bg-well' : 'border-line hover:border-line-strong'"
                @click="toggle(draft.bindings, r.key)"
              >
                <span class="flex items-center gap-1.5">
                  <span
                    class="grid h-3.5 w-3.5 place-items-center rounded-[4px] border"
                    :class="draft.bindings.includes(r.key) ? 'border-ink bg-ink text-paper' : 'border-line-strong'"
                  >
                    <AppIcon v-if="draft.bindings.includes(r.key)" name="check" :size="9" />
                  </span>
                  <span class="font-mono text-[12px]">{{ r.key }}</span>
                </span>
                <span class="mt-1 block truncate font-mono text-[10.5px] text-ink-faint">
                  {{ r.capabilities.join(' · ') || '没有能力' }}
                </span>
              </button>
            </div>
            <p v-else class="text-[11.5px] text-ink-faint">
              这个部署里还没有插件声明资源。所有工具都在默认目标上。
            </p>
          </div>

          <!-- 权限 -->
          <div>
            <div class="mb-1.5 flex items-center gap-2">
              <span class="text-[11.5px] text-ink-soft">给它哪些权限</span>
              <span class="text-[11px] text-ink-faint">不勾就是一把只能认路的钥匙</span>
            </div>
            <div class="flex flex-wrap gap-1.5">
              <button
                v-for="p in permissions"
                :key="p.key"
                type="button"
                class="chip transition-colors"
                :class="draft.permissions.includes(p.key) ? 'border-ink/30 bg-ink text-paper' : 'hover:border-line-strong'"
                :title="p.key"
                @click="toggle(draft.permissions, p.key)"
              >
                {{ p.description }}
              </button>
            </div>
          </div>

          <!-- 工具白名单:收窄到其中几个 -->
          <div>
            <div class="mb-1.5 flex items-center gap-2">
              <span class="text-[11.5px] text-ink-soft">再收窄到哪几个工具</span>
              <span class="text-[11px] text-ink-faint">不勾 = 按权限给全部</span>
            </div>
            <div class="space-y-1.5">
              <div v-if="mutatingTools.length" class="flex flex-wrap items-center gap-1.5">
                <span class="mono-label w-14 shrink-0">改世界</span>
                <button
                  v-for="t in mutatingTools"
                  :key="t.name"
                  type="button"
                  class="chip transition-colors"
                  :class="draft.tools.includes(t.name) ? 'border-ink/30 bg-ink text-paper' : 'hover:border-line-strong'"
                  :title="`${t.name} · 需要 ${t.permission}`"
                  @click="toggle(draft.tools, t.name)"
                >
                  {{ t.label }}
                </button>
              </div>
              <div v-if="readonlyTools.length" class="flex flex-wrap items-center gap-1.5">
                <span class="mono-label w-14 shrink-0">只看</span>
                <button
                  v-for="t in readonlyTools"
                  :key="t.name"
                  type="button"
                  class="chip font-mono text-[11px] transition-colors"
                  :class="draft.tools.includes(t.name) ? 'border-ink/30 bg-ink text-paper' : 'hover:border-line-strong'"
                  :title="`${t.name} · 需要 ${t.permission}`"
                  @click="toggle(draft.tools, t.name)"
                >
                  {{ t.name }}
                </button>
              </div>
              <p v-if="!toolsOnSelectedResources().length" class="text-[11.5px] text-ink-faint">
                选中的资源上还没有可用工具。
              </p>
            </div>
          </div>

          <!-- 签发前先看见对方会拿到什么 -->
          <div class="rounded-card border border-line bg-well/60 px-3 py-2.5">
            <div class="flex items-center gap-2">
              <span class="text-[11.5px] text-ink-soft">按上面的勾选,这个 agent 的工具清单</span>
              <span class="chip ml-auto">{{ preview.length }} 个</span>
            </div>
            <div class="mt-1.5 flex flex-wrap gap-1">
              <span
                v-for="t in preview"
                :key="t.name"
                class="chip font-mono text-[10.5px]"
                :class="t.mutating ? 'chip-bad' : ''"
              >
                {{ t.name }}
              </span>
              <span v-if="!preview.length" class="text-[11.5px] text-ink-faint">
                什么都没有。这样签出去的钥匙认得路,但调不动任何工具。
              </span>
            </div>
          </div>

          <p v-if="formError" class="text-[11.5px] text-coral">{{ formError }}</p>

          <div class="flex items-center gap-2">
            <button
              class="btn-solid h-9 px-3.5 text-[12.5px]"
              :disabled="issuing || !draft.name.trim()"
              @click="submit"
            >
              {{ issuing ? '签发中…' : '签发' }}
            </button>
            <span class="text-[11px] text-ink-faint">
              签出去的权限不会超过你手上的;租户取自你,调用时盖过工具参数。
            </span>
          </div>
        </div>

        <!-- 明文只出现这一次 -->
        <div
          v-if="fresh"
          class="mx-5 mb-4 rounded-card border border-amber/30 bg-amber/5 px-3 py-3"
        >
          <div class="text-[12px] font-medium">「{{ fresh.name }}」的密钥,现在复制走</div>
          <p class="mt-1 text-[11.5px] text-ink-soft">
            这一行只出现这一次,关掉就再也拿不到;丢了就吊销重签,没有第二种处理。
          </p>
          <div class="mt-2 flex items-center gap-2">
            <code class="min-w-0 flex-1 truncate rounded-card border border-line bg-well px-2 py-1.5 font-mono text-[11.5px]">{{ fresh.key }}</code>
            <button class="btn-outline h-8 px-3 text-[12px]" @click="copy(fresh.key, 'key')">
              {{ copied === 'key' ? '已复制' : '复制' }}
            </button>
            <button class="btn-ghost h-8 px-2 text-[12px]" @click="fresh = null">收起</button>
          </div>
        </div>
      </section>

      <!-- 三、清单 -->
      <section class="panel overflow-hidden">
        <div class="flex items-center gap-2 border-b border-line px-5 py-3.5">
          <AppIcon name="list-checks" :size="14" class="text-ink-faint" />
          <h2 class="text-[13px] font-semibold">密钥清单</h2>
          <span class="eyebrow ml-auto">{{ activeKeys.length }} 把在用</span>
        </div>

        <div v-if="activeKeys.length" class="divide-y divide-line/60">
          <article v-for="k in activeKeys" :key="k.id" class="px-5 py-3.5">
            <div class="flex flex-wrap items-center gap-2">
              <span class="text-[12.5px] font-medium">{{ k.name || '未具名' }}</span>
              <span class="font-mono text-[11px] text-ink-faint">{{ k.hint }}</span>
              <span v-if="k.created_by" class="chip">由 {{ k.created_by }} 签</span>
              <span v-if="k.expires_at" class="chip chip-warn">到期 {{ when(k.expires_at) }}</span>
              <span v-if="k.last_used_at" class="chip ml-auto">最近用过 {{ when(k.last_used_at) }}</span>
              <span v-else class="chip ml-auto">没用过</span>
              <button
                v-if="canManage"
                class="btn-ghost h-7 px-2 text-[11.5px] text-coral"
                :disabled="revoking === k.id"
                @click="onRevoke(k)"
              >
                {{ revoking === k.id ? '吊销中…' : '吊销' }}
              </button>
            </div>

            <div class="mt-2 flex flex-wrap items-center gap-1">
              <span class="mono-label mr-1">资源</span>
              <span v-for="b in k.bindings" :key="b" class="chip font-mono text-[10.5px]">{{ b }}</span>
              <span v-if="!k.bindings.length" class="chip">不限</span>
            </div>
            <div class="mt-1 flex flex-wrap items-center gap-1">
              <span class="mono-label mr-1">权限</span>
              <span v-for="p in k.permissions" :key="p" class="chip">{{ permissionLabel(p) }}</span>
              <span v-if="!k.permissions.length" class="chip chip-warn">没有权限</span>
            </div>
            <div v-if="k.tools.length" class="mt-1 flex flex-wrap items-center gap-1">
              <span class="mono-label mr-1">只给了</span>
              <span v-for="t in k.tools" :key="t" class="chip font-mono text-[10.5px]">{{ t }}</span>
            </div>
          </article>
        </div>

        <EmptyState
          v-else
          icon="key-round"
          title="还没有密钥"
          hint="签一把,外界的 agent 就能接上来了。"
        />

        <details v-if="revokedKeys.length" class="border-t border-line/60">
          <summary class="cursor-pointer px-5 py-3 text-[11.5px] text-ink-faint hover:text-ink-soft">
            已吊销 {{ revokedKeys.length }} 把(记录留着:谁签的、什么时候用过)
          </summary>
          <div class="divide-y divide-line/40">
            <div
              v-for="k in revokedKeys"
              :key="k.id"
              class="flex flex-wrap items-center gap-2 px-5 py-2.5 text-[11.5px] text-ink-faint"
            >
              <span class="font-medium text-ink-soft">{{ k.name || '未具名' }}</span>
              <span class="font-mono text-[11px]">{{ k.hint }}</span>
              <span v-if="k.created_by">由 {{ k.created_by }} 签</span>
              <span v-if="k.last_used_at" class="ml-auto">最后用过 {{ when(k.last_used_at) }}</span>
            </div>
          </div>
        </details>
      </section>
    </template>
  </div>
</template>
