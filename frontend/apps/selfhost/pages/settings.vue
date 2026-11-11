<script setup lang="ts">
import { useSettings } from '@gwei/core/composables/useSettings'
import { useTheme } from '@gwei/core/composables/useTheme'
import { SettingsScopesApi } from '@gwei/core/api/client'

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
              <span class="mb-1 flex items-center gap-1.5 text-[11.5px] text-ink-soft">
                {{ f.name }}
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
              <span
                v-if="f.description"
                class="mt-1 block text-[11px] text-ink-faint"
              >{{ f.description }}</span>
              <span
                v-if="f.set && f.expose !== 'never' && f.value"
                class="mt-1 block truncate text-[11px] text-ink-faint"
              >当前：{{ f.value }}</span>
            </label>
          </div>

          <div class="mt-3 flex items-center gap-2">
            <button
              class="btn-solid h-8 px-3 text-[12px]"
              :disabled="saving === s.name"
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
    </template>
  </div>
</template>