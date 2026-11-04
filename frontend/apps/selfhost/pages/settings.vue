<script setup lang="ts">
import { useSettings } from '@gwei/core/composables/useSettings'

const { data, loading, error } = useSettings()

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
  <div class="space-y-4">
    <header>
      <div class="mono-label">SETTINGS</div>
      <h1 class="mt-1.5 text-[27px] font-semibold leading-none tracking-tightest">设置</h1>
      <p class="mt-2 text-[12.5px] text-ink-soft">当前租户的运行参数与接入方式。</p>
    </header>

    <div v-if="error" class="card border-coral/30 bg-coral/5 p-4 text-[12.5px] text-coral">
      拉不到设置。确认引擎在跑,或开启 mock 模式。
    </div>

    <div v-if="loading && !data" class="grid gap-4 sm:grid-cols-2">
      <div v-for="i in 4" :key="i" class="h-[170px] animate-pulse rounded-panel bg-well/60" />
    </div>

    <div v-else-if="data" class="grid gap-4 sm:grid-cols-2">
      <section
        v-for="section in sections"
        :key="section.title"
        class="overflow-hidden rounded-panel border border-line bg-panel"
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
          <span
            v-for="c in section.chips"
            :key="c"
            class="rounded-full border border-line bg-well px-2.5 py-1 font-mono text-[10.5px] text-ink-soft"
          >
            {{ c }}
          </span>
        </div>
      </section>
    </div>
  </div>
</template>
