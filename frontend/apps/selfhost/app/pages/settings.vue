<script setup lang="ts">
import { useSettings } from '@gwei/core/composables/useSettings'
import { useTheme } from '@gwei/core/composables/useTheme'
import { ApiKeysApi, SettingsScopesApi } from '@gwei/core/api/client'

interface ScopeField {
  name: string
  required: boolean
  expose: string
  set: boolean
  value: string | null
  description: string
  /** 值带换行(私钥):用多行输入,单行输入会在粘贴时把换行吃掉 */
  multiline: boolean
}
interface Scope {
  name: string
  prefix: string
  fields: ScopeField[]
  missing: string[]
}

const { data, loading, error } = useSettings()
const { mode, set } = useTheme()

// 接入层配置:字段、必填、回显规则都由引擎声明,这里不预设任何密钥名。
const scopes = ref<Scope[]>([])
const saving = ref<string | null>(null)
const scopeErrorText = ref('')
const drafts = reactive<Record<string, Record<string, string>>>({})
const savedScope = ref<string | null>(null)

// 草稿只在用户输入时写;渲染期不创建/修改状态。
function setDraft(scope: string, field: string, value: string) {
  if (!drafts[scope]) drafts[scope] = {}
  drafts[scope][field] = value
}

function draftValue(scope: string, field: string): string {
  return drafts[scope]?.[field] ?? ''
}

// 接口给的是人话(字段 + 应该怎么填);这里只去掉 "API error: 422" 这种前缀。
function friendly(raw: string): string {
  return raw.replace(/^API error:\s*\d{3}\s*/, '').trim()
}

async function loadScopes() {
  try {
    scopes.value = (await SettingsScopesApi.list()) as unknown as Scope[]
  } catch (e) {
    scopeErrorText.value = friendly(e instanceof Error ? e.message : String(e))
  }
}

// 只在浏览器里拉数据:渲染期不发起同源请求,SSR 不依赖它。
onMounted(loadScopes)

// 没有写权限就只读:按钮禁掉,后端也会拦(403)
const { can } = useAuth()
const canWriteSettings = computed(() => can('settings.write'))

async function onSave(name: string) {
  const values = Object.fromEntries(
    Object.entries(drafts[name] || {}).filter(([, v]) => v !== ''),
  )
  if (!Object.keys(values).length) return
  saving.value = name
  scopeErrorText.value = ''
  try {
    await SettingsScopesApi.put(name, values)
    drafts[name] = {}
    savedScope.value = name
    await loadScopes()
    setTimeout(() => {
      if (savedScope.value === name) savedScope.value = null
    }, 2000)
  } catch (e) {
    scopeErrorText.value = friendly(e instanceof Error ? e.message : String(e))
  } finally {
    saving.value = null
  }
}

const themes = [
  { key: 'light' as const, icon: 'sun', label: '亮色', hint: '纸面底色，白天看' },
  { key: 'dark' as const, icon: 'moon', label: '暗色', hint: '夜里值守时看' },
  { key: 'system' as const, icon: 'system', label: '跟随系统', hint: '跟着系统切换' },
]

// ---- MCP 接入:给外界的 agent 签一把钥匙 ---------------------------------
// 一把密钥有什么权限,它的 tools/list 里就只有什么工具 —— 这里只签与撤,
// 不做"先看后给"的两步:签发那一次就能看到明文,之后永远只有 hint。

interface IssuedKey {
  id: string
  name: string
  hint: string
  permissions: string[]
  tools: string[]
  created_at: string
  last_used_at: string
  expires_at: string
  key?: string
}
interface PermissionOption { key: string, description: string }

const keys = ref<IssuedKey[]>([])
const permissionOptions = ref<PermissionOption[]>([])
const keysError = ref('')
const issuing = ref(false)
const revoking = ref<string | null>(null)
const freshKey = ref<{ name: string, key: string } | null>(null)
const draft = reactive({ name: '', permissions: [] as string[] })

// 演示模式没有引擎,也就没有可签的凭据:整块不出现,免得点一下报一串 404
const useMock = useRuntimeConfig().public.useMock === true
const canManageKeys = computed(() => can('keys.manage'))
const canReadKeys = computed(() => !useMock && (can('keys.read') || canManageKeys.value))

async function loadKeys() {
  if (!canReadKeys.value) return
  try {
    const [listed, permissions] = await Promise.all([
      ApiKeysApi.list(),
      $fetch<{ permissions: PermissionOption[] }>('/api/permissions'),
    ])
    keys.value = (listed.items as unknown as IssuedKey[]) ?? []
    permissionOptions.value = permissions.permissions
  } catch (e) {
    keysError.value = friendly(e instanceof Error ? e.message : String(e))
  }
}

function toggleKeyPermission(key: string) {
  const i = draft.permissions.indexOf(key)
  if (i >= 0) draft.permissions.splice(i, 1)
  else draft.permissions.push(key)
}

function keyPermissionLabel(key: string): string {
  return permissionOptions.value.find(p => p.key === key)?.description ?? key
}

async function issueKey() {
  issuing.value = true
  keysError.value = ''
  try {
    const issued = await ApiKeysApi.issue({
      name: draft.name,
      permissions: draft.permissions,
    })
    const body = issued as unknown as IssuedKey
    freshKey.value = { name: body.name, key: body.key ?? '' }
    draft.name = ''
    draft.permissions = []
    await loadKeys()
  } catch (e) {
    keysError.value = friendly(e instanceof Error ? e.message : String(e))
  } finally {
    issuing.value = false
  }
}

async function revokeKey(id: string) {
  revoking.value = id
  keysError.value = ''
  try {
    await ApiKeysApi.revoke(id)
    await loadKeys()
  } catch (e) {
    keysError.value = friendly(e instanceof Error ? e.message : String(e))
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

onMounted(loadKeys)

const sections = computed(() => {
  const d = data.value
  if (!d) return []
  return [
    {
      icon: 'users',
      title: '团队',
      rows: [
        { k: '团队名称', v: d.teamName },
        { k: '成员', v: d.memberCount + ' 人' },
        { k: '管理员', v: d.adminCount + ' 人' },
      ],
    },
    {
      icon: 'layers',
      title: '订阅',
      rows: [
        { k: '档位', v: d.plan },
        { k: '价格', v: d.planPrice },
        { k: '议题配额', v: d.issueQuota },
      ],
    },
    {
      icon: 'bell',
      title: '通知',
      rows: [],
      chips: d.notificationChannels,
    },
    {
      icon: 'shield-check',
      title: '单点登录',
      rows: [{ k: '提供方', v: d.ssoProvider }],
    },
  ]
})
</script>

<template>
  <div class="space-y-5">
    <PageHeader
      eyebrow="SETTINGS"
      title="设置"
      description="当前租户的运行参数与接入方式。"
    />

    <div v-if="error" class="panel border-coral/30 bg-coral/5 p-4 text-[12.5px] text-coral">
      拉不到设置。确认引擎在跑，或开启 mock 模式。
    </div>

    <div v-if="loading && !data" class="grid gap-4 sm:grid-cols-2">
      <div v-for="i in 4" :key="i" class="h-[170px] skeleton" />
    </div>

    <template v-else-if="data">
      <!-- 外观 -->
      <section class="panel overflow-hidden">
        <div class="flex items-center gap-2 border-b border-line px-5 py-3.5">
          <AppIcon name="palette" :size="14" class="text-ink-faint" />
          <h2 class="text-[13px] font-semibold">外观</h2>
          <span class="eyebrow ml-auto">APPEARANCE</span>
        </div>

        <div class="grid gap-3 p-5 sm:grid-cols-3">
          <button
            v-for="t in themes"
            :key="t.key"
            class="flex items-center gap-3 rounded-card border px-4 py-3 text-left transition-colors duration-200 ease-[var(--ease)]"
            :class="mode === t.key ? 'border-ink/30 bg-well' : 'border-line hover:border-line-strong'"
            @click="set(t.key)"
          >
            <span
              class="grid h-8 w-8 shrink-0 place-items-center rounded-full transition-colors duration-200"
              :class="mode === t.key ? 'bg-ink text-paper' : 'bg-panel text-ink-faint'"
            >
              <AppIcon :name="t.icon" :size="14" />
            </span>
            <span class="min-w-0">
              <span class="block text-[13px] font-medium">{{ t.label }}</span>
              <span class="block truncate text-[12px] text-ink-faint">{{ t.hint }}</span>
            </span>
          </button>
        </div>
      </section>

      <div class="grid gap-4 sm:grid-cols-2">
        <section
          v-for="section in sections"
          :key="section.title"
          class="panel overflow-hidden"
        >
          <div class="flex items-center gap-2 border-b border-line px-5 py-3.5">
            <AppIcon :name="section.icon" :size="14" class="text-ink-faint" />
            <h2 class="text-[13px] font-semibold">{{ section.title }}</h2>
          </div>

          <div
            v-for="row in section.rows"
            :key="row.k"
            class="flex items-center justify-between gap-4 border-b border-line/60 px-5 py-3 last:border-0"
          >
            <span class="text-[12.5px] text-ink-soft">{{ row.k }}</span>
            <span class="text-[12.5px] font-medium">{{ row.v }}</span>
          </div>

          <div v-if="section.chips?.length" class="flex flex-wrap gap-1.5 px-5 py-4">
            <span v-for="c in section.chips" :key="c" class="chip">{{ c }}</span>
          </div>
        </section>
      </div>

      <!-- 接入与密钥:哪些字段、能不能回显,由引擎的声明决定 -->
      <section class="panel overflow-hidden">
        <div class="flex items-center gap-2 border-b border-line px-5 py-3.5">
          <AppIcon name="shield-check" :size="14" class="text-ink-faint" />
          <h2 class="text-[13px] font-semibold">接入与密钥</h2>
          <span class="eyebrow ml-auto">INTEGRATIONS</span>
        </div>

        <div
          v-for="s in scopes"
          :key="s.name"
          class="border-b border-line/60 px-5 py-4 last:border-0"
        >
          <div class="flex items-center gap-2">
            <span class="text-[12.5px] font-medium">{{ s.name }}</span>
            <span v-if="s.prefix" class="chip">{{ s.prefix }}</span>
            <span v-if="s.missing.length" class="ml-auto text-[11.5px] text-ink-faint">
              缺 {{ s.missing.join('、') }}
            </span>
          </div>

          <div class="mt-3 grid gap-2 sm:grid-cols-2">
            <label
              v-for="f in s.fields"
              :key="f.name"
              class="block"
              :class="f.multiline ? 'sm:col-span-2' : ''"
            >
              <!-- 主标题用人话(引擎给的说明),字段名退成下方的小字:
                   一屏密钥字段光看 webhook_secret 这种名字,不知道自己在填什么。 -->
              <span class="mb-1 flex items-center gap-1.5 text-[11.5px] text-ink-soft">
                {{ f.description || f.name }}
                <span v-if="f.required" class="text-coral">*</span>
              </span>
              <textarea
                v-if="f.multiline"
                :value="draftValue(s.name, f.name)"
                @input="setDraft(s.name, f.name, ($event.target as HTMLTextAreaElement).value)"
                :placeholder="f.set ? '已设置，留空不修改' : '未设置'"
                rows="6"
                class="w-full resize-y rounded-card border border-line bg-well px-3 py-2 font-mono text-[11.5px] leading-relaxed outline-none focus:border-line-strong"
                autocomplete="off"
                spellcheck="false"
              />
              <input
                v-else
                :value="draftValue(s.name, f.name)"
                @input="setDraft(s.name, f.name, ($event.target as HTMLInputElement).value)"
                :type="f.expose === 'never' ? 'password' : 'text'"
                :placeholder="f.set ? '已设置，留空不修改' : '未设置'"
                class="w-full rounded-card border border-line bg-well px-3 py-2 text-[12.5px] outline-none focus:border-line-strong"
                autocomplete="off"
              >
              <span class="mt-1 flex items-center gap-2 font-mono text-[10.5px] text-ink-faint">
                <span>{{ f.name }}</span>
                <span
                  class="rounded px-1 py-px"
                  :class="f.set ? 'bg-well text-ink-soft' : 'text-ink-faint/70'"
                >{{ f.set ? '已设置' : '未设置' }}</span>
              </span>
              <span
                v-if="f.set && f.expose !== 'never' && f.value"
                class="mt-1 block truncate text-[11px] text-ink-faint"
              >当前：{{ f.value }}</span>
            </label>
          </div>

          <div class="mt-3 flex items-center gap-2">
            <button
              class="btn-solid h-8 px-3 text-[12px]"
              :disabled="saving === s.name || !canWriteSettings"
              @click="onSave(s.name)"
            >
              {{ saving === s.name ? '保存中…' : '保存' }}
            </button>
            <span v-if="savedScope === s.name" class="text-[11.5px] text-ink-faint">已保存</span>
          </div>
        </div>

        <div
          v-if="scopeErrorText"
          class="mx-5 my-3 rounded-card border border-coral/30 bg-coral/5 px-3 py-2 text-[12px] text-coral"
        >
          {{ scopeErrorText }}
        </div>

        <div v-if="!scopes.length" class="px-5 py-6 text-[12.5px] text-ink-faint">
          还没有接入层声明任何配置项。
        </div>
      </section>

      <!-- MCP 接入:外界 agent 拿一把密钥接上 /mcp,工具按这把密钥的权限暴露 -->
      <section v-if="canReadKeys" class="panel overflow-hidden">
        <div class="flex items-center gap-2 border-b border-line px-5 py-3.5">
          <AppIcon name="key-round" :size="14" class="text-ink-faint" />
          <h2 class="text-[13px] font-semibold">MCP 接入</h2>
          <span class="eyebrow ml-auto">AGENT ACCESS</span>
        </div>

        <div class="border-b border-line/60 px-5 py-4">
          <p class="text-[12.5px] leading-relaxed text-ink-soft">
            把地址贴进 Claude Code、Cursor 或任何支持 MCP 的客户端,凭据填一把密钥。
            密钥有什么权限,工具清单里就只有什么工具。
          </p>
          <div class="mt-3 grid gap-2 sm:grid-cols-2">
            <div class="rounded-card border border-line bg-well px-3 py-2">
              <span class="block text-[11px] text-ink-faint">地址(streamable HTTP)</span>
              <button class="mt-0.5 block w-full truncate text-left font-mono text-[12px]" @click="copy(mcpUrl, 'url')">
                {{ mcpUrl }}
              </button>
            </div>
            <div class="rounded-card border border-line bg-well px-3 py-2">
              <span class="block text-[11px] text-ink-faint">凭据请求头</span>
              <span class="mt-0.5 block font-mono text-[12px]">X-Gwei-Token: &lt;密钥&gt;</span>
            </div>
          </div>
          <div v-if="copied" class="mt-2 text-[11.5px] text-ink-faint">已复制</div>
        </div>

        <!-- 签发 -->
        <div v-if="canManageKeys" class="border-b border-line/60 px-5 py-4">
          <div class="flex flex-wrap items-end gap-2">
            <label class="min-w-[180px] flex-1">
              <span class="mb-1 block text-[11.5px] text-ink-soft">这把密钥给谁用</span>
              <input
                v-model="draft.name"
                placeholder="例:claude-code 本机"
                class="w-full rounded-card border border-line bg-well px-3 py-2 text-[12.5px] outline-none focus:border-line-strong"
                autocomplete="off"
              >
            </label>
            <button
              class="btn-solid h-9 px-3.5 text-[12.5px]"
              :disabled="issuing || !draft.name.trim()"
              @click="issueKey"
            >
              {{ issuing ? '签发中…' : '签发密钥' }}
            </button>
          </div>

          <div class="mt-3">
            <span class="mb-1.5 block text-[11.5px] text-ink-soft">
              给它哪些权限
              <span class="text-ink-faint">(不勾就是一把只能认路的钥匙,调不动任何工具)</span>
            </span>
            <div class="flex flex-wrap gap-1.5">
              <button
                v-for="p in permissionOptions"
                :key="p.key"
                class="chip transition-colors"
                :class="draft.permissions.includes(p.key) ? 'border-ink/30 bg-ink text-paper' : 'hover:border-line-strong'"
                :title="p.key"
                @click="toggleKeyPermission(p.key)"
              >
                {{ p.description }}
              </button>
            </div>
          </div>
        </div>

        <!-- 明文只出现这一次 -->
        <div
          v-if="freshKey"
          class="mx-5 my-3 rounded-card border border-amber/30 bg-amber/5 px-3 py-3"
        >
          <div class="text-[12px] font-medium">「{{ freshKey.name }}」的密钥,现在复制走</div>
          <p class="mt-1 text-[11.5px] text-ink-soft">
            这一行只出现这一次,关掉页面就再也拿不到;丢了就吊销重签。
          </p>
          <div class="mt-2 flex items-center gap-2">
            <code class="min-w-0 flex-1 truncate rounded-card border border-line bg-well px-2 py-1.5 font-mono text-[11.5px]">{{ freshKey.key }}</code>
            <button class="btn-outline h-8 px-3 text-[12px]" @click="copy(freshKey.key, 'key')">复制</button>
            <button class="btn-ghost h-8 px-2 text-[12px]" @click="freshKey = null">收起</button>
          </div>
        </div>

        <!-- 清单 -->
        <div v-if="keys.length" class="divide-y divide-line/60">
          <div v-for="k in keys" :key="k.id" class="px-5 py-3">
            <div class="flex items-center gap-2">
              <span class="text-[12.5px] font-medium">{{ k.name || '未具名' }}</span>
              <span class="font-mono text-[11px] text-ink-faint">{{ k.hint }}</span>
              <span v-if="k.last_used_at" class="chip ml-auto">
                最近用过 {{ k.last_used_at.slice(0, 16).replace('T', ' ') }}
              </span>
              <span v-else class="chip ml-auto">没用过</span>
              <button
                v-if="canManageKeys"
                class="btn-ghost h-7 px-2 text-[11.5px] text-coral"
                :disabled="revoking === k.id"
                @click="revokeKey(k.id)"
              >
                {{ revoking === k.id ? '吊销中…' : '吊销' }}
              </button>
            </div>
            <div class="mt-1.5 flex flex-wrap gap-1">
              <span v-for="p in k.permissions" :key="p" class="chip">{{ keyPermissionLabel(p) }}</span>
              <span v-if="!k.permissions.length" class="chip chip-warn">没有权限</span>
            </div>
          </div>
        </div>

        <div v-else class="px-5 py-6 text-[12.5px] text-ink-faint">
          还没有密钥。签一把,外界的 agent 就能接上来了。
        </div>

        <div
          v-if="keysError"
          class="mx-5 my-3 rounded-card border border-coral/30 bg-coral/5 px-3 py-2 text-[12px] text-coral"
        >
          {{ keysError }}
        </div>
      </section>

      <PluginSlot slot="settings.plugins" empty-hint="插件可以在这里放自己的设置面板。" />
    </template>
  </div>
</template>