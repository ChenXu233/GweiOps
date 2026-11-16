<script setup lang="ts">
import { useSettings } from '@gwei/core/composables/useSettings'
import { useTheme } from '@gwei/core/composables/useTheme'
import { SettingsScopesApi, ReleaseSettingsApi } from '@gwei/core/api/client'

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

// 发布配置:租户默认与仓库行,一层一份 JSON 声明;生效值由引擎四层合并算好。
// 页面先给 effective 兜底——没配任何东西时展示的也是「现在实际会怎样」,不是空白。
interface ReleaseRepoRow {
  set: boolean
  values: Record<string, string>
  effective: Record<string, string>
}
interface ReleaseConfig {
  fields: Record<string, string>
  modes: string[]
  compose_required: string[]
  effective: Record<string, string>
  tenant_default: { set: boolean; values: Record<string, string> }
  repos: Record<string, ReleaseRepoRow>
}

const release = ref<ReleaseConfig | null>(null)
const releaseLoading = ref(false)
const releaseError = ref('')
const releaseSaved = ref<string | null>(null)
const releaseDrafts = reactive<Record<string, Record<string, string>>>({})
const newRepo = ref('')
const releaseExpanded = reactive<Record<string, boolean>>({})

function releaseDraft(key: string, field: string): string {
  return releaseDrafts[key]?.[field] ?? ''
}

function setReleaseDraft(key: string, field: string, value: string) {
  if (!releaseDrafts[key]) releaseDrafts[key] = {}
  releaseDrafts[key][field] = value
}

function releaseEffective(key: string): Record<string, string> {
  if (key === '*') return release.value?.effective ?? {}
  return release.value?.repos[key]?.effective ?? release.value?.effective ?? {}
}

async function loadRelease() {
  releaseLoading.value = true
  releaseError.value = ''
  try {
    release.value = (await ReleaseSettingsApi.get()) as unknown as ReleaseConfig
  } catch (e) {
    releaseError.value = friendly(e instanceof Error ? e.message : String(e))
  } finally {
    releaseLoading.value = false
  }
}

async function saveReleaseRow(key: string) {
  const values = Object.fromEntries(
    Object.entries(releaseDrafts[key] || {}).filter(([, v]) => v !== ''),
  )
  if (!Object.keys(values).length) return
  releaseError.value = ''
  try {
    if (key === '*') await ReleaseSettingsApi.putTenantDefault(values)
    else await ReleaseSettingsApi.putRepo(key, values)
    delete releaseDrafts[key]
    releaseSaved.value = key
    await loadRelease()
    setTimeout(() => {
      if (releaseSaved.value === key) releaseSaved.value = null
    }, 2000)
  } catch (e) {
    releaseError.value = friendly(e instanceof Error ? e.message : String(e))
  }
}

async function removeReleaseRow(key: string) {
  releaseError.value = ''
  try {
    if (key === '*') await ReleaseSettingsApi.deleteTenantDefault()
    else await ReleaseSettingsApi.deleteRepo(key)
    delete releaseDrafts[key]
    await loadRelease()
  } catch (e) {
    releaseError.value = friendly(e instanceof Error ? e.message : String(e))
  }
}

function addRepoRow() {
  const repo = newRepo.value.trim()
  if (!repo || !repo.includes('/') || repo in (release.value?.repos ?? {})) return
  newRepo.value = ''
  releaseExpanded[repo] = true
  loadRelease().then(() => {
    if (!release.value?.repos[repo]) {
      release.value = release.value
        ? { ...release.value, repos: { ...release.value.repos, [repo]: { set: false, values: {}, effective: release.value.effective } } }
        : release.value
    }
  })
}

// ---- 注册与账号核验 ------------------------------------------------------
// 注册默认关着(引擎侧默认 false)。这里改的是"这台实例允不允许自助注册",
// 逐键覆盖进配置 scope registration,引擎按它算出生效策略。
interface RegPolicy {
  enabled: boolean
  methods: string[]
  requires_verification: boolean
  code_ttl_minutes: number
  oidc: { available: boolean, label: string }
}
const regPolicy = ref<RegPolicy | null>(null)
const regDraft = reactive<Record<string, string>>({})
const regBusy = ref(false)
const regMsg = ref('')
const regErr = ref('')

const REG_FIELDS = [
  { key: 'registration_enabled', label: '允许自助注册', hint: '关掉之后只有管理员能在成员页加人' },
  { key: 'registration_methods', label: '注册方式', hint: 'email / phone / oidc,逗号分隔' },
  { key: 'registration_requires_verification', label: '注册必须核验', hint: '关掉就是填了就能进,只建议在完全内网时用' },
  { key: 'registration_default_role', label: '默认角色', hint: '新注册用户自动接上的角色 key' },
  { key: 'registration_public_base_url', label: '前台地址', hint: '邮件链接与 OIDC 回跳用;留空按请求 Host 推' },
] as const

async function loadRegistration() {
  const [pol, scope] = await Promise.all([
    $fetch<RegPolicy>('/api/auth/registration/policy').catch(() => null),
    SettingsScopesApi.list().catch(() => [] as unknown[]),
  ])
  regPolicy.value = pol
  // 已保存的值只在配置 scope 里;接口回显的是"生效值",所以这里读 scope 的当前值
  const found = (scope as unknown as Scope[]).find((x) => x.name === 'registration')
  if (found) {
    for (const f of found.fields) {
      if (f.value !== null) regDraft[f.name] = f.value
    }
  }
}

async function saveRegistration() {
  const values = Object.fromEntries(Object.entries(regDraft).filter(([, v]) => v !== ''))
  if (!Object.keys(values).length) return
  regBusy.value = true
  regErr.value = ''
  regMsg.value = ''
  try {
    await SettingsScopesApi.put('registration', values)
    regMsg.value = '已保存,下一次请求就按新策略走'
    for (const k of Object.keys(regDraft)) delete regDraft[k]
    await loadRegistration()
  } catch (e) {
    regErr.value = friendly(e instanceof Error ? e.message : String(e))
  } finally {
    regBusy.value = false
  }
}

// ---- 配额 ----------------------------------------------------------------
// 限量按 数量/窗口 声明(2000/30d);用的是已落账的用量,不另存计数器。
interface QuotaItem { resource: string, used: number, limit: number, window_hours: number, remaining: number | null }
const quota = ref<{ tenant: string, items: QuotaItem[] } | null>(null)
const quotaDraft = reactive<Record<string, string>>({})
const quotaErr = ref('')
// 只管这三个:别的资源要限量时在配置里加键,页面不重新发明一遍
const QUOTA_FIELDS = ['issues', 'llm_tokens', 'agent_runs'] as const
const quotaMsg = ref('')

async function loadQuota() {
  try {
    const [usage, scopes] = await Promise.all([
      $fetch<{ tenant: string, items: QuotaItem[] }>('/api/quota', { query: { tenant: 'default' } }).catch(() => null),
      SettingsScopesApi.list().catch(() => [] as unknown[]),
    ])
    quota.value = usage
    const found = (scopes as unknown as Scope[]).find((x) => x.name === 'quota')
    if (found) {
      for (const f of found.fields) {
        if (f.value !== null) quotaDraft[f.name] = f.value
      }
    }
  } catch (e) {
    quotaErr.value = friendly(e instanceof Error ? e.message : String(e))
  }
}

async function saveQuota() {
  const values = Object.fromEntries(Object.entries(quotaDraft).filter(([, v]) => v !== ''))
  if (!Object.keys(values).length) return
  quotaErr.value = ''
  quotaMsg.value = ''
  try {
    await SettingsScopesApi.put('quota', values)
    quotaMsg.value = '已保存'
    for (const k of Object.keys(quotaDraft)) delete quotaDraft[k]
    await loadQuota()
  } catch (e) {
    quotaErr.value = friendly(e instanceof Error ? e.message : String(e))
  }
}

function quotaPercent(item: QuotaItem): number {
  if (!item.window_hours || item.limit <= 0) return 0
  return Math.min(100, Math.round((item.used / item.limit) * 100))
}

// 接入层配置:字段、必填、回显规则都由引擎声明,这里不预设任何密钥名。
const scopes = ref<Scope[]>([])
const saving = ref<string | null>(null)
const scopeErrorText = ref('')
// 值存下来了,但配置推送失败(进程外插件靠核心推配置)
const pushWarning = ref('')
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

// 接口给的是人话(字段 + 应该怎么填);这里只去掉 "API error: 422" 前缀。
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
onMounted(() => {
  loadScopes()
  loadRelease()
  loadRegistration()
  loadQuota()
})

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
  pushWarning.value = ''
  try {
    const saved = (await SettingsScopesApi.put(name, values)) as unknown as {
      push_error?: string
    }
    drafts[name] = {}
    savedScope.value = name
    // 值存下了,但插件手里还是旧配置:这不是保存失败,也不能只说"已保存"
    pushWarning.value = saved?.push_error || ''
    await loadScopes()
    setTimeout(() => {
      if (savedScope.value === name) savedScope.value = null
    }, 2000)
  } catch (e) {
    pushWarning.value = ''
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

// MCP 接入有自己的页面:签密钥要挑资源、勾权限、看它拿到什么清单,塞在设置页里
// 会把"当前租户的运行参数"和"给外界发凭据"混成一件事。
const hasKeyAccess = computed(() => can('keys.read'))
const mockMode = useRuntimeConfig().public.useMock === true

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

      <!-- 发布配置:租户默认与仓库行。生效值兜底展示,填了才产生覆盖 -->
      <section class="panel overflow-hidden">
        <div class="flex items-center gap-2 border-b border-line px-5 py-3.5">
          <AppIcon name="rocket" :size="14" class="text-ink-faint" />
          <h2 class="text-[13px] font-semibold">发布配置</h2>
          <span class="eyebrow ml-auto">RELEASE</span>
        </div>

        <div class="border-b border-line/60 px-5 py-4">
          <p class="text-[12px] text-ink-soft">
            每个仓库按「出厂默认 → 部署环境 → 租户默认 → 仓库行」逐键合并;下面已显示合并后的生效值,
            留空的项不产生覆盖。发布模式 off = 合并只记报告,compose = 走发布管道。
          </p>
        </div>

        <div v-if="releaseLoading && !release" class="px-5 py-6">
          <div class="h-4 w-48 skeleton" />
        </div>

        <template v-if="release">
          <!-- 生效值:现在实际会怎样 -->
          <div class="border-b border-line/60 px-5 py-4">
            <div class="flex items-center gap-2">
              <span class="text-[12.5px] font-medium">当前生效</span>
              <span class="chip">{{ release.effective.mode }}</span>
              <span v-if="release.effective.mode === 'compose' && release.compose_required.some((k) => !release?.effective[k])" class="text-[11.5px] text-coral">
                compose 必填项缺失
              </span>
            </div>
            <div class="mt-2 grid gap-x-6 gap-y-1 sm:grid-cols-2">
              <div
                v-for="(desc, field) in release.fields"
                :key="field"
                class="flex items-baseline justify-between gap-3"
              >
                <span class="text-[11.5px] text-ink-faint">{{ desc }}</span>
                <span class="truncate font-mono text-[11.5px]">{{ releaseEffective('*')[field] || '—' }}</span>
              </div>
            </div>
          </div>

          <!-- 租户默认 -->
          <div class="border-b border-line/60 px-5 py-4">
            <div class="flex items-center gap-2">
              <button
                class="text-[12.5px] font-medium hover:underline"
                @click="releaseExpanded['*'] = !releaseExpanded['*']"
              >租户默认</button>
              <span class="chip" :class="release.tenant_default.set ? '' : 'text-ink-faint/70'">
                {{ release.tenant_default.set ? '已覆盖' : '未配置(走环境/出厂)' }}
              </span>
              <button
                v-if="release.tenant_default.set"
                class="ml-auto text-[11.5px] text-coral hover:underline"
                :disabled="!canWriteSettings"
                @click="removeReleaseRow('*')"
              >删除此层</button>
            </div>
            <div v-if="releaseExpanded['*']" class="mt-3 grid gap-2 sm:grid-cols-2">
              <label v-for="(desc, field) in release.fields" :key="field" class="block">
                <span class="mb-1 block text-[11.5px] text-ink-soft">{{ desc }}</span>
                <input
                  :value="releaseDraft('*', field)"
                  @input="setReleaseDraft('*', field, ($event.target as HTMLInputElement).value)"
                  :placeholder="release.tenant_default.values[field] || releaseEffective('*')[field] || ''"
                  class="w-full rounded-card border border-line bg-well px-3 py-2 font-mono text-[11.5px] outline-none focus:border-line-strong"
                  autocomplete="off"
                  spellcheck="false"
                >
              </label>
              <div class="sm:col-span-2">
                <button
                  class="btn-solid h-8 px-3 text-[12px]"
                  :disabled="!canWriteSettings"
                  @click="saveReleaseRow('*')"
                >保存租户默认</button>
              </div>
            </div>
          </div>

          <!-- 仓库行 -->
          <div
            v-for="(row, repo) in release.repos"
            :key="repo"
            class="border-b border-line/60 px-5 py-4 last:border-0"
          >
            <div class="flex items-center gap-2">
              <button
                class="font-mono text-[12.5px] font-medium hover:underline"
                @click="releaseExpanded[repo] = !releaseExpanded[repo]"
              >{{ repo }}</button>
              <span class="chip">{{ row.effective.mode }}</span>
              <span class="chip" :class="row.set ? '' : 'text-ink-faint/70'">
                {{ row.set ? '已覆盖' : '未配置(继承上层)' }}
              </span>
              <button
                v-if="row.set"
                class="ml-auto text-[11.5px] text-coral hover:underline"
                :disabled="!canWriteSettings"
                @click="removeReleaseRow(repo)"
              >删除此行</button>
            </div>
            <div v-if="releaseExpanded[repo]" class="mt-3 grid gap-2 sm:grid-cols-2">
              <label v-for="(desc, field) in release.fields" :key="field" class="block">
                <span class="mb-1 block text-[11.5px] text-ink-soft">{{ desc }}</span>
                <input
                  :value="releaseDraft(repo, field)"
                  @input="setReleaseDraft(repo, field, ($event.target as HTMLInputElement).value)"
                  :placeholder="row.values[field] || row.effective[field] || ''"
                  class="w-full rounded-card border border-line bg-well px-3 py-2 font-mono text-[11.5px] outline-none focus:border-line-strong"
                  autocomplete="off"
                  spellcheck="false"
                >
              </label>
              <div class="sm:col-span-2">
                <button
                  class="btn-solid h-8 px-3 text-[12px]"
                  :disabled="!canWriteSettings"
                  @click="saveReleaseRow(repo)"
                >保存 {{ repo }}</button>
                <span v-if="releaseSaved === repo" class="ml-2 text-[11.5px] text-ink-faint">已保存</span>
              </div>
            </div>
          </div>

          <!-- 新增仓库行 -->
          <div class="flex items-center gap-2 border-b border-line/60 px-5 py-4 last:border-0">
            <input
              v-model="newRepo"
              placeholder="owner/repo — 给单个仓库加覆盖行"
              class="w-64 rounded-card border border-line bg-well px-3 py-2 font-mono text-[11.5px] outline-none focus:border-line-strong"
              autocomplete="off"
              spellcheck="false"
              @keyup.enter="addRepoRow"
            >
            <button
              class="btn-solid h-8 px-3 text-[12px]"
              :disabled="!canWriteSettings || !newRepo.includes('/')"
              @click="addRepoRow"
            >展开新仓库行</button>
            <span class="text-[11.5px] text-ink-faint">行保存后才真正落库</span>
          </div>
        </template>

        <div
          v-if="releaseError"
          class="mx-5 my-3 rounded-card border border-coral/30 bg-coral/5 px-3 py-2 text-[12px] text-coral"
        >
          {{ releaseError }}
        </div>
      </section>

      <!-- 注册与账号核验:开关、方式、核验通道都在这 -->
      <section class="panel overflow-hidden">
        <div class="flex items-center gap-2 border-b border-line px-5 py-3.5">
          <AppIcon name="users" :size="14" class="text-ink-faint" />
          <h2 class="text-[13px] font-semibold">注册与账号核验</h2>
          <span class="chip ml-auto">
            {{ regPolicy?.enabled ? '已开启' : '未开启' }}
          </span>
        </div>

        <div class="border-b border-line/60 px-5 py-4">
          <p class="text-[12px] text-ink-soft">
            注册默认关闭,自部署与 SaaS 都按这个开关走。现在生效的方式:
            <span class="font-mono">{{ regPolicy?.methods.join(', ') || '—' }}</span>
            <span v-if="regPolicy?.oidc.available">,统一身份已配好</span>。
            核验通道(邮件 / 短信)在下方「接入与密钥」的 email / sms 里填;没配通道时注册会如实拒绝,
            不会静默跳过核验。
          </p>
        </div>

        <div class="grid gap-2 px-5 py-4 sm:grid-cols-2">
          <label v-for="f in REG_FIELDS" :key="f.key" class="block">
            <span class="mb-1 block text-[11.5px] text-ink-soft">{{ f.label }}</span>
            <input
              :value="regDraft[f.key] ?? ''"
              :placeholder="f.hint"
              :disabled="!canWriteSettings"
              class="w-full rounded-card border border-line bg-well px-3 py-2 text-[12.5px] outline-none focus:border-line-strong"
              autocomplete="off"
              @input="regDraft[f.key] = ($event.target as HTMLInputElement).value"
            >
          </label>
        </div>

        <div class="flex items-center gap-2 px-5 pb-4">
          <button class="btn-solid h-8 px-3 text-[12px]" :disabled="regBusy || !canWriteSettings" @click="saveRegistration">
            {{ regBusy ? '保存中…' : '保存注册设置' }}
          </button>
          <span v-if="regMsg" class="text-[11.5px] text-ink-faint">{{ regMsg }}</span>
        </div>

        <div v-if="regErr" class="mx-5 mb-4 rounded-card border border-coral/30 bg-coral/5 px-3 py-2 text-[12px] text-coral">
          {{ regErr }}
        </div>
      </section>

      <!-- 配额:限量按 数量/窗口 声明,用量读已落账的每一笔 -->
      <section class="panel overflow-hidden">
        <div class="flex items-center gap-2 border-b border-line px-5 py-3.5">
          <AppIcon name="layers" :size="14" class="text-ink-faint" />
          <h2 class="text-[13px] font-semibold">配额</h2>
          <span class="eyebrow ml-auto">QUOTA</span>
        </div>

        <div v-for="item in quota?.items ?? []" :key="item.resource" class="border-b border-line/60 px-5 py-3">
          <div class="flex items-baseline justify-between gap-3">
            <span class="font-mono text-[12px]">{{ item.resource }}</span>
            <span class="text-[11.5px] text-ink-soft">
              {{ item.window_hours ? `${item.used} / ${item.limit} (每 ${item.window_hours}h)` : '不限' }}
            </span>
          </div>
          <div v-if="item.window_hours" class="mt-1.5 h-1 overflow-hidden rounded-full bg-well">
            <div
              class="h-full rounded-full transition-all"
              :class="quotaPercent(item) >= 100 ? 'bg-coral' : 'bg-ink/70'"
              :style="{ width: quotaPercent(item) + '%' }"
            />
          </div>
        </div>

        <div class="grid gap-2 px-5 py-4 sm:grid-cols-3">
          <label v-for="item in QUOTA_FIELDS" :key="item" class="block">
            <span class="mb-1 block text-[11.5px] text-ink-soft">{{ item }}</span>
            <input
              :value="quotaDraft[item] ?? ''"
              placeholder="2000/30d"
              :disabled="!canWriteSettings"
              class="w-full rounded-card border border-line bg-well px-3 py-2 font-mono text-[11.5px] outline-none focus:border-line-strong"
              autocomplete="off"
              @input="quotaDraft[item] = ($event.target as HTMLInputElement).value"
            >
          </label>
        </div>

        <div class="flex items-center gap-2 px-5 pb-4">
          <button class="btn-solid h-8 px-3 text-[12px]" :disabled="!canWriteSettings" @click="saveQuota">保存配额</button>
          <span v-if="quotaMsg" class="text-[11.5px] text-ink-faint">{{ quotaMsg }}</span>
          <span class="text-[11.5px] text-ink-faint">留空 = 用平台默认</span>
        </div>

        <div v-if="quotaErr" class="mx-5 mb-4 rounded-card border border-coral/30 bg-coral/5 px-3 py-2 text-[12px] text-coral">
          {{ quotaErr }}
        </div>
      </section>

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
          v-if="pushWarning"
          class="mx-5 my-3 rounded-card border border-amber/30 bg-amber/5 px-3 py-2 text-[12px] text-ink-soft"
        >
          已存下,但没推给插件:{{ pushWarning }}
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

      <!-- MCP 接入在它自己的页面上:那里要挑资源、勾权限、看工具清单 -->
      <section v-if="hasKeyAccess" class="panel overflow-hidden">
        <div class="flex items-center gap-2 border-b border-line px-5 py-3.5">
          <AppIcon name="key-round" :size="14" class="text-ink-faint" />
          <h2 class="text-[13px] font-semibold">MCP 接入</h2>
          <span class="eyebrow ml-auto">AGENT ACCESS</span>
        </div>
        <div class="flex flex-wrap items-center gap-3 px-5 py-4">
          <div class="min-w-0 flex-1">
            <p class="text-[12.5px] leading-relaxed text-ink-soft">
              外界的 agent 用一把密钥接上 <code class="font-mono text-[11.5px]">/mcp</code>。
              密钥有什么权限、能碰哪些资源,它的工具清单里就只有哪些。
            </p>
            <p v-if="mockMode" class="mt-1 text-[11.5px] text-ink-faint">
              演示模式没有引擎,也就没有可签的凭据。
            </p>
          </div>
          <NuxtLink to="/mcp" class="btn-outline btn-sm shrink-0">
            管理密钥
            <AppIcon name="arrow-right" :size="13" />
          </NuxtLink>
        </div>
      </section>

      <PluginSlot slot="settings.plugins" empty-hint="插件可以在这里放自己的设置面板。" />
    </template>
  </div>
</template>