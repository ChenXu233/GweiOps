<script setup lang="ts">
interface NavItem {
  href: string
  label: string
  icon: string
  modes?: string[]
}

const mode = useRuntimeConfig().public.mode as string

// modes: 该入口仅在指定部署档位显示(缺省全档可见)
const navItems: NavItem[] = [
  { href: '/dashboard', label: '态势感知', icon: '📊' },
  { href: '/repos', label: '仓库', icon: '📦' },
  { href: '/issues', label: 'Issues', icon: '🎫' },
  { href: '/changes', label: '变更账本', icon: '📘' },
  { href: '/marketplace', label: '插件', icon: '🧩' },
  { href: '/settings', label: '设置', icon: '⚙️' },
]
const visibleItems = navItems.filter(
  item => !item.modes || item.modes.includes(mode)
)
</script>

<template>
  <div class="flex h-screen">
    <aside class="w-56 border-r border-border bg-card flex flex-col">
      <div class="p-4 border-b border-border">
        <NuxtLink to="/dashboard" class="flex items-center gap-2">
          <span class="text-xl font-bold tracking-tight">既未 · Gwei</span>
        </NuxtLink>
      </div>
      <nav class="flex-1 p-2 space-y-0.5">
        <NuxtLink
          v-for="item in visibleItems"
          :key="item.href"
          :to="item.href"
          class="flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors hover:bg-accent hover:text-accent-foreground text-muted-foreground"
        >
          <span class="text-base">{{ item.icon }}</span>
          {{ item.label }}
        </NuxtLink>
      </nav>
      <div class="p-4 border-t border-border">
        <div v-if="mode === 'saas'" class="flex items-center gap-3">
          <div class="h-8 w-8 rounded-full bg-muted flex items-center justify-center text-xs font-semibold">
            AC
          </div>
          <div class="text-sm">
            <div class="font-medium">Acme Corp</div>
            <div class="text-xs text-muted-foreground">专业版</div>
          </div>
        </div>
        <div v-else class="flex items-center gap-2 text-xs text-muted-foreground">
          <span class="h-1.5 w-1.5 rounded-full bg-green-500" />
          Self-hosted
        </div>
      </div>
    </aside>
    <main class="flex-1 overflow-auto">
      <div class="p-6">
        <slot />
      </div>
    </main>
  </div>
</template>
