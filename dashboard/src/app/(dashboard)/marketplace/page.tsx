'use client'

import { Button } from '@/components/ui/button'
import { usePlugins } from '@/features/repos/hooks'
import { cn } from '@/lib/utils'

export default function MarketplacePage() {
  const { data: plugins, isLoading } = usePlugins()

  if (isLoading) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold tracking-tight">插件市场</h1>
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-px bg-border rounded-lg overflow-hidden">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-48 bg-card animate-pulse" />
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold tracking-tight">插件市场</h1>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-px bg-border rounded-lg overflow-hidden">
        {plugins?.map((plugin) => (
          <div key={plugin.id} className="bg-card p-5 flex flex-col">
            <div className="text-2xl mb-3">{plugin.icon}</div>
            <div className="text-sm font-semibold mb-1">{plugin.name}</div>
            <p className="text-xs text-muted-foreground leading-relaxed mb-3 flex-1">{plugin.description}</p>
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-muted-foreground">
                {plugin.author === 'official' ? '官方' : '社区'}
                {plugin.price !== null && ` · $${plugin.price}/月`}
                {plugin.price === null && ' · 免费'}
              </span>
              <Button variant={plugin.installed ? 'outline' : 'default'} size="sm" className={cn('text-[11px] h-7', plugin.installed && 'border-green-500/30 text-green-500')}>
                {plugin.installed ? '已安装' : '安装'}
              </Button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
