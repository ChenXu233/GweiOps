<script setup lang="ts">
import { navGroups, useNavCounts, usePalette } from '~/composables/useNavigation'
import { useSettings } from '@gwei/core/composables/useSettings'

defineProps<{ open: boolean }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const route = useRoute()
const { countFor } = useNavCounts()
const { show: showPalette } = usePalette()
const { data: settings } = useSettings()
// 谁在操作。首屏没有就拉一次;退出按钮走同一个 composable。
const { user, load: loadUser, logout } = useAuth()
onMounted(() => {
  if (!user.value) loadUser()
})

const collapsed = useState<boolean>('gwei-nav-collapsed', () => false)

// 收成图标轨只在大屏成立:窄屏侧边是抽屉,永远整宽带文字。
const isDesktop = ref(false)
const rail = computed(() => collapsed.value && isDesktop.value)

let mq: MediaQueryList | null = null
function sync() {
  isDesktop.value = mq?.matches ?? false
}

function isActive(to: string) {
  return route.path === to || route.path.startsWith(to + '/')
}

function toggleCollapsed() {
  collapsed.value = !collapsed.value
  persist()
}

function persist() {
  if (!import.meta.client) return
  try {
    localStorage.setItem('gwei-nav-collapsed', collapsed.value ? '1' : '0')
  } catch {
    // 隐私模式下写不进去,折叠状态退化为会话内
  }
}

onMounted(() => {
  try {
    const raw = localStorage.getItem('gwei-nav-collapsed')
    if (raw !== null) collapsed.value = raw === '1'
  } catch {
    // 读不到就用默认展开
  }
  mq = window.matchMedia('(min-width: 1024px)')
  sync()
  mq.addEventListener('change', sync)
})

onUnmounted(() => mq?.removeEventListener('change', sync))
</script>

<template>
  <aside
    class="fixed inset-y-0 left-0 z-50 flex h-[100dvh] flex-col overflow-hidden border-r border-line/70 bg-panel/85 backdrop-blur-xl transition-[width,transform] duration-300 ease-[var(--ease)]"
    :class="[
      rail ? 'lg:w-[68px]' : 'w-[244px]',
      open ? 'translate-x-0' : '-translate-x-full',
      'lg:translate-x-0',
    ]"
  >
    <!-- 品牌 + 收起 -->
    <div
      class="flex h-14 shrink-0 items-center gap-2 px-3"
      :class="rail ? 'lg:justify-center lg:px-0' : ''"
    >
      <NuxtLink to="/dashboard" class="flex min-w-0 items-center gap-2.5" aria-label="既未 Gwei Ops">
        <span class="relative grid h-7 w-7 shrink-0 place-items-center rounded-[9px] bg-ink text-paper">
          <span class="font-mono text-[11.5px] font-semibold leading-none">未</span>
          <span class="absolute right-[3px] top-[3px] h-[5px] w-[5px] rounded-full bg-lime" />
        </span>
        <span v-if="!rail" class="min-w-0">
          <span class="block truncate text-[15px] font-semibold leading-none tracking-tightest">既未</span>
          <span class="mono-label mt-1 block">GWEI OPS</span>
        </span>
      </NuxtLink>

      <button
        v-if="!rail"
        class="btn-icon ml-auto"
        aria-label="收起侧边栏"
        title="收起侧边栏"
        @click="toggleCollapsed"
      >
        <AppIcon name="panel-left" :size="15" />
      </button>
    </div>

    <!-- 搜索 -->
    <div class="shrink-0 px-3" :class="rail ? 'lg:px-3.5' : ''">
      <button
        class="flex w-full items-center rounded-xl border border-line bg-panel/70 text-ink-faint transition-colors duration-200 ease-[var(--ease)] hover:border-line-strong hover:text-ink"
        :class="rail ? 'h-9 justify-center' : 'h-9 gap-2 px-2.5'"
        aria-label="搜索页面"
        @click="showPalette()"
        @mousedown="emit('close')"
      >
        <AppIcon name="search" :size="15" />
        <template v-if="!rail">
          <span class="flex-1 truncate text-left text-[12.5px]">搜索页面</span>
          <span class="kbd">Ctrl K</span>
        </template>
      </button>
    </div>

    <!-- 导航 -->
    <nav class="min-h-0 flex-1 overflow-y-auto overflow-x-hidden px-3 pb-2 pt-2" :class="rail ? 'lg:px-3.5' : ''">
      <div v-for="(group, gi) in navGroups" :key="group.title">
        <p v-if="!rail" class="nav-section" :class="gi === 0 ? 'pt-2' : ''">{{ group.title }}</p>
        <div v-else class="mx-auto my-2 h-px w-6 bg-line/70" :class="gi === 0 ? 'mt-1' : ''" />

        <ul class="space-y-1">
          <li v-for="item in group.items" :key="item.to">
            <NuxtLink
              :to="item.to"
              class="nav-link"
              :class="[
                isActive(item.to) ? 'nav-link-active' : '',
                rail ? 'relative mx-auto h-9 w-9 justify-center px-0' : '',
              ]"
              :title="rail ? item.label : item.hint"
              @click="emit('close')"
            >
              <span class="relative grid place-items-center">
                <AppIcon :name="item.icon" :size="16" />
                <!-- 图标轨:只用一个小点表示"有事等你",数字放不下 -->
                <span
                  v-if="rail && countFor(item.badge)"
                  class="absolute -right-1 -top-0.5 h-[6px] w-[6px] rounded-full ring-2"
                  :class="isActive(item.to) ? 'bg-amber ring-ink' : 'bg-amber ring-paper'"
                />
              </span>
              <template v-if="!rail">
                <span class="flex-1 truncate">{{ item.label }}</span>
                <span
                  v-if="countFor(item.badge)"
                  class="num shrink-0 rounded-full px-1.5 py-0.5 font-mono text-[11px] leading-none"
                  :class="isActive(item.to) ? 'bg-paper/20 text-paper' : 'bg-amber/15 text-amber'"
                >
                  {{ countFor(item.badge) }}
                </span>
              </template>
            </NuxtLink>
          </li>
        </ul>
      </div>
    </nav>

    <!-- 底部:外观 + 租户(图标轨只留两个按钮) -->
    <div class="shrink-0 border-t border-line/70" :class="rail ? 'px-2.5 py-2' : 'p-2.5'">
      <div v-if="rail" class="flex flex-col items-center gap-1.5">
        <ThemeSwitch collapsed />
        <button
          class="grid h-9 w-9 place-items-center rounded-xl text-ink-faint transition-colors duration-200 ease-[var(--ease)] hover:bg-well hover:text-ink"
          aria-label="展开侧边栏"
          title="展开侧边栏"
          @click="toggleCollapsed"
        >
          <AppIcon name="panel-left" :size="16" class="rotate-180" />
        </button>
      </div>

      <template v-else>
        <ThemeSwitch />

        <div class="mt-2 flex items-center gap-2.5 rounded-xl border border-line-soft bg-well/60 px-2.5 py-2">
          <span
            class="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-ink text-[11.5px] font-semibold text-paper"
          >
            {{ (user?.name || settings?.teamName || '当').slice(0, 1) }}
          </span>
          <div class="min-w-0 flex-1">
            <div class="truncate text-[12.5px] font-medium leading-tight">
              {{ user?.name || settings?.teamName || '当前租户' }}
            </div>
            <div class="mono-label mt-1 truncate">
              {{ user?.is_sub_user ? '子账号' : '所有者' }} · {{ user?.tenant || settings?.plan || 'SELFHOST' }}
            </div>
          </div>
          <button
            type="button"
            title="退出登录"
            class="grid h-7 w-7 shrink-0 place-items-center rounded-lg text-ink-faint hover:bg-line/40 hover:text-ink"
            @click="logout"
          >
            <AppIcon name="log-out" :size="14" />
          </button>
        </div>
      </template>
    </div>
  </aside>
</template>