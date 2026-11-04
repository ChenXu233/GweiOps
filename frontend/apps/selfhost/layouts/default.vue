<script setup lang="ts">
const { mode, set, init } = useTheme()
const route = useRoute()
const config = useRuntimeConfig()

onMounted(init)

interface NavItem {
  to: string
  label: string
  icon: string
}

const nav: NavItem[] = [
  { to: '/dashboard', label: '控制室', icon: 'dashboard' },
  { to: '/repos', label: '仓库', icon: 'repos' },
  { to: '/issues', label: '议题', icon: 'issues' },
  { to: '/changes', label: '变更账本', icon: 'changes' },
  { to: '/marketplace', label: '插件', icon: 'plugins' },
  { to: '/settings', label: '设置', icon: 'settings' },
]

const themes = [
  { key: 'light' as const, icon: 'sun', label: '亮色' },
  { key: 'dark' as const, icon: 'moon', label: '暗色' },
  { key: 'system' as const, icon: 'system', label: '跟随系统' },
]

const paletteOpen = ref(false)

const modeLabel = computed(() => (config.public.mode === 'saas' ? 'SaaS' : '单租户自部署'))

function isActive(to: string) {
  return route.path === to || route.path.startsWith(to + '/')
}

function onHotkey(e: KeyboardEvent) {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    paletteOpen.value = !paletteOpen.value
  }
}

onMounted(() => window.addEventListener('keydown', onHotkey))
onUnmounted(() => window.removeEventListener('keydown', onHotkey))
</script>

<template>
  <div class="flex min-h-screen flex-col bg-paper text-ink">
    <header class="glass-bar sticky top-0 z-40 border-b border-line/60">
      <div class="mx-auto flex h-14 w-full max-w-[1180px] items-center gap-4 px-5">
        <NuxtLink to="/dashboard" class="flex shrink-0 items-center gap-2.5" aria-label="既未 Gwei Ops">
          <span class="relative grid h-7 w-7 place-items-center rounded-[9px] bg-ink text-paper">
            <span class="font-mono text-[11px] font-semibold leading-none">未</span>
            <span class="absolute right-[3px] top-[3px] h-[5px] w-[5px] rounded-full bg-lime" />
          </span>
          <span class="text-[15px] font-semibold tracking-tightest">既未</span>
          <span class="mono-label hidden xl:inline">GWEI OPS</span>
        </NuxtLink>

        <nav class="hidden items-center gap-0.5 md:flex">
          <NuxtLink
            v-for="item in nav"
            :key="item.to"
            :to="item.to"
            class="flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[13px] font-medium transition-colors"
            :class="isActive(item.to) ? 'bg-ink text-paper' : 'text-ink-soft hover:bg-well hover:text-ink'"
          >
            <AppIcon :name="item.icon" :size="14" />
            {{ item.label }}
          </NuxtLink>
        </nav>

        <div class="ml-auto flex items-center gap-2">
          <button
            class="hidden items-center gap-2 rounded-full border border-line bg-panel/80 py-1.5 pl-2.5 pr-1.5 text-ink-faint transition-colors hover:border-ink/20 hover:text-ink sm:flex"
            aria-label="搜索页面"
            @click="paletteOpen = true"
          >
            <AppIcon name="search" :size="13" />
            <span class="text-[12px]">跳转</span>
            <span class="kbd">Ctrl K</span>
          </button>

          <div class="flex items-center gap-0.5 rounded-full border border-line bg-panel/80 p-0.5">
            <button
              v-for="t in themes"
              :key="t.key"
              class="grid h-7 w-7 place-items-center rounded-full transition-colors"
              :class="mode === t.key ? 'bg-ink text-paper' : 'text-ink-faint hover:text-ink'"
              :aria-label="t.label"
              :title="t.label"
              @click="set(t.key)"
            >
              <AppIcon :name="t.icon" :size="13" />
            </button>
          </div>
        </div>
      </div>

      <div class="no-scrollbar flex gap-1 overflow-x-auto border-t border-line/60 px-4 py-2 md:hidden">
        <NuxtLink
          v-for="item in nav"
          :key="item.to"
          :to="item.to"
          class="flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-[12px] font-medium"
          :class="isActive(item.to) ? 'bg-ink text-paper' : 'text-ink-soft'"
        >
          <AppIcon :name="item.icon" :size="13" />
          {{ item.label }}
        </NuxtLink>
      </div>
    </header>

    <main class="mx-auto w-full max-w-[1180px] flex-1 px-5 pb-20 pt-7">
      <slot />
    </main>

    <footer class="border-t border-line/60">
      <div class="mx-auto flex w-full max-w-[1180px] flex-wrap items-center justify-between gap-2 px-5 py-6">
        <span class="mono-label">既未 · GWEI OPS</span>
        <span class="mono-label">{{ modeLabel }} · v0.1.0</span>
      </div>
    </footer>

    <CommandPalette v-if="paletteOpen" :items="nav" @close="paletteOpen = false" />
  </div>
</template>
