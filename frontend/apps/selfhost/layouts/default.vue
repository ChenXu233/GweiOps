<script setup lang="ts">
const navItems = [
  { href: '/dashboard', label: '态势感知', icon: '📊' },
  { href: '/repos', label: '仓库', icon: '📦' },
  { href: '/issues', label: 'Issues', icon: '🎫' },
  { href: '/marketplace', label: '插件', icon: '🧩' },
  { href: '/settings', label: '设置', icon: '⚙️' },
]
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
          v-for="item in navItems"
          :key="item.href"
          :to="item.href"
          class="flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors hover:bg-accent hover:text-accent-foreground text-muted-foreground"
        >
          <span class="text-base">{{ item.icon }}</span>
          {{ item.label }}
        </NuxtLink>
      </nav>
      <div class="p-4 border-t border-border">
        <div class="flex items-center gap-3">
          <div class="h-8 w-8 rounded-full bg-muted flex items-center justify-center text-xs font-semibold">
            AC
          </div>
          <div class="text-sm">
            <div class="font-medium">Acme Corp</div>
            <div class="text-xs text-muted-foreground">专业版</div>
          </div>
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
