<script setup lang="ts">
// 界面路由的前缀:`/workspaces/{slug}/issues`。
//
// 工作区是一个资源,资源要有 URL —— 所以它出现在路径里,而不是 cookie 里。
// 后端那一侧同理(`/api/workspaces/{slug}/…`),两边对齐,分享出去的链接才
// 自带"这是哪一道账"。
//
// 一个只属于一个工作区的人不必每条链接都带那一段:不带也能打开,引擎按他最早的
// 那条成员关系回答。
import { navGroups, usePalette } from '~/composables/useNavigation'
import { useTheme } from '@gwei/core/composables/useTheme'
import { useWorkspaces } from '@gwei/core/composables/useWorkspaces'

const route = useRoute()
const config = useRuntimeConfig()

// `useWorkspaces` 里那份是同一张表:列表、当前选中、以及把工作区补进接口路径
// 的读法都在那儿,这里只是把路由那一段抄进去。
const { current, items, select, syncFromRoute, hrefFor } = useWorkspaces()

const { init } = useTheme()
const { open: paletteOpen, show: showPalette, hide: hidePalette, toggle: togglePalette } = usePalette()
const mobileNavOpen = ref(false)
const collapsed = useState<boolean>('gwei-nav-collapsed', () => false)

const modeLabel = computed(() => (config.public.mode === 'saas' ? 'SaaS' : '单租户自部署'))

// 地址里那一段工作区,没有就是空串。
const scopedSlug = computed(() => {
  const parts = route.path.split('/').filter(Boolean)
  return parts[0] === 'workspaces' ? parts[1] ?? '' : ''
})

// 状态跟着路由走:路由里那段是唯一真相源,别处只读它。
watch(
  () => route.fullPath,
  () => syncFromRoute(),
  { immediate: true },
)

onMounted(() => init())

// 地址里没有工作区段时,等列表回来再把它补进地址:刷新、收藏、分享都是同一道账。
// 挂载那一刻列表通常还没回来,所以不能在 onMounted 里做。
// 地址里已经有、而且确实是他工作区之一时不动 —— 刚点的切换器自己负责导航。
// 包里的那个已经不在了(被移出)也走这里:地址要说他真正在看的那一道账。
watch(
  () => current.value?.slug,
  (slug) => {
    if (!slug || scopedSlug.value === slug) return
    if (items.value.some((w) => w.slug === scopedSlug.value)) return
    const parts = route.path.split('/').filter(Boolean)
    const rest = scopedSlug.value ? parts.slice(2) : parts
    const tail = rest.length ? `/${rest.join('/')}` : '/issues'
    // 先把"当前这道账"定下来,再换地址:新页面挂载时读工作区的那一层不能还是空的,
    // 否则它这一轮请求会落到"他最早的那条成员关系"上。
    select(slug)
    navigateTo(`/workspaces/${encodeURIComponent(slug)}${tail}`, { replace: true })
  },
)

function onHotkey(e: KeyboardEvent) {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    togglePalette()
  }
}

onMounted(() => window.addEventListener('keydown', onHotkey))
onUnmounted(() => window.removeEventListener('keydown', onHotkey))
</script>

<template>
  <div class="min-h-screen bg-paper text-ink">
    <!-- 移动端:侧边栏浮在内容之上 -->
    <Transition
      enter-active-class="transition-opacity duration-200"
      enter-from-class="opacity-0"
      leave-active-class="transition-opacity duration-150"
      leave-to-class="opacity-0"
    >
      <div
        v-if="mobileNavOpen"
        class="fixed inset-0 z-40 bg-ink/25 backdrop-blur-sm lg:hidden"
        @click="mobileNavOpen = false"
      />
    </Transition>

    <AppSidebar :open="mobileNavOpen" @close="mobileNavOpen = false" />

    <div
      class="transition-[padding] duration-300 ease-[var(--ease)]"
      :class="collapsed ? 'lg:pl-[68px]' : 'lg:pl-[244px]'"
    >
      <!-- 顶栏:导航已全部搬进侧边,这里只留全局动作 -->
      <header class="glass-bar sticky top-0 z-30 border-b border-line/60">
        <div class="flex h-14 items-center gap-3 px-5">
          <button
            class="btn-icon lg:hidden"
            aria-label="打开导航"
            @click="mobileNavOpen = true"
          >
            <AppIcon name="menu" :size="17" />
          </button>

          <span class="chip hidden gap-1.5 sm:inline-flex">
            <span class="dot bg-ok" />
            {{ modeLabel }}
          </span>

          <div class="ml-auto flex items-center gap-2">
            <button class="btn-outline btn-sm hidden sm:inline-flex" @click="showPalette()">
              <AppIcon name="search" :size="13" />
              搜索
              <span class="kbd">Ctrl K</span>
            </button>
            <button class="btn-icon sm:hidden" aria-label="搜索页面" @click="showPalette()">
              <AppIcon name="search" :size="16" />
            </button>
            <StatusPip tone="ok" pulse label="引擎在线" />
          </div>
        </div>
      </header>

      <main class="app-bg min-h-[calc(100vh-3.5rem)] px-5 pb-16 pt-6">
        <div class="mx-auto w-full max-w-[1180px]">
          <slot />
        </div>
      </main>

      <footer class="border-t border-line/60">
        <div class="mx-auto flex w-full max-w-[1180px] flex-wrap items-center justify-between gap-2 px-5 py-6">
          <span class="mono-label">既未 · GWEI OPS</span>
          <span class="mono-label">摆渡未济,恒守既济。</span>
        </div>
      </footer>
    </div>

    <CommandPalette v-if="paletteOpen" :groups="navGroups" :resolve-to="hrefFor" @close="hidePalette()" />

    <!-- 右下角悬浮区:挂什么由插件决定(默认是控制台助手),装没装由引擎说 -->
    <PluginDock />
  </div>
</template>
