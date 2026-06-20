'use client'

import { useTeamSettings } from '@/features/repos/hooks'

export default function SettingsPage() {
  const { data: settings, isLoading } = useTeamSettings()

  if (isLoading || !settings) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold tracking-tight">系统设置</h1>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-px bg-border rounded-lg overflow-hidden">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-24 bg-card animate-pulse" />
          ))}
        </div>
      </div>
    )
  }

  const cards = [
    { label: '团队', value: settings.teamName, sub: `${settings.memberCount} 名成员 · ${settings.adminCount} 管理员` },
    { label: '订阅套餐', value: settings.plan, sub: `${settings.planPrice} · ${settings.issueQuota}` },
    { label: '通知渠道', value: settings.notificationChannels.join(' · '), sub: '紧急事件同时推送所有渠道' },
    { label: 'SSO', value: settings.ssoProvider, sub: '团队成员通过 GitHub 登录' },
  ]

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold tracking-tight">系统设置</h1>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-px bg-border rounded-lg overflow-hidden">
        {cards.map((card) => (
          <div key={card.label} className="bg-card p-5">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-2">{card.label}</div>
            <div className="text-sm font-medium">{card.value}</div>
            <div className="text-xs text-muted-foreground mt-1">{card.sub}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
