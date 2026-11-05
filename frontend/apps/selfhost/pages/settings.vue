<script setup lang="ts">
import { useSettings } from '@gwei/core/composables/useSettings'
import { useTheme } from '@gwei/core/composables/useTheme'

const { data, loading, error } = useSettings()
const { mode, set } = useTheme()

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
    </template>
  </div>
</template>