<template>
  <div class="space-y-6">
    <h1 class="text-2xl font-bold tracking-tight">系统设置</h1>

    <!-- Skeleton loader -->
    <div v-if="loading" class="grid grid-cols-1 md:grid-cols-2 gap-px bg-border rounded-lg overflow-hidden">
      <div v-for="i in 4" :key="i" class="h-24 bg-card animate-pulse" />
    </div>

    <!-- Content -->
    <div v-else class="grid grid-cols-1 md:grid-cols-2 gap-px bg-border rounded-lg overflow-hidden">
      <div
        v-for="card in cards"
        :key="card.label"
        class="bg-card p-5"
      >
        <div class="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-2">
          {{ card.label }}
        </div>
        <div class="text-sm font-medium">
          {{ card.value }}
        </div>
        <div class="text-xs text-muted-foreground mt-1">
          {{ card.sub }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const { data: settings, loading } = useSettings()

const cards = computed(() => {
  if (!settings.value) return []
  const s = settings.value
  return [
    {
      label: '团队',
      value: s.teamName,
      sub: `${s.memberCount} 名成员 · ${s.adminCount} 管理员`,
    },
    {
      label: '订阅套餐',
      value: s.plan,
      sub: `${s.planPrice} · ${s.issueQuota}`,
    },
    {
      label: '通知渠道',
      value: s.notificationChannels.join(' · '),
      sub: '紧急事件同时推送所有渠道',
    },
    {
      label: 'SSO',
      value: s.ssoProvider,
      sub: '团队成员通过 GitHub 登录',
    },
  ]
})
</script>
