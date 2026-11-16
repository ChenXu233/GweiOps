<script setup lang="ts">
// 侧边栏最上面那个"我现在在哪个工作区"。
//
// 它不是一个筛选框:工作区是数据边界,换一个就是换一整套议题、账本、配置与
// 成员。所以它放在导航之上、永远可见,而不是收进某个下拉筛选里。
import { useWorkspaces } from '@gwei/core/composables/useWorkspaces'

defineProps<{ rail?: boolean }>()

const { items, current, select } = useWorkspaces()
const open = ref(false)

async function pick(slug: string) {
  select(slug)
  open.value = false
  // 换了工作区就是换了数据:留在原页面等于看一个不属于这个工作区的列表。
  await navigateTo('/issues')
}

onClickOutsideOrEsc()
function onClickOutsideOrEsc() {
  if (!import.meta.client) return
  const close = () => (open.value = false)
  onMounted(() => {
    window.addEventListener('click', close)
    window.addEventListener('keydown', (e) => e.key === 'Escape' && close())
  })
}
</script>

<template>
  <!-- 图标轨:只留一个字母与一个小点,点开是同一个菜单 -->
  <button
    v-if="rail"
    class="mx-auto grid h-9 w-9 place-items-center rounded-xl border border-line/70 bg-well/60 text-[12px] font-semibold"
    :title="current?.name || '工作区'"
    @click.stop="open = !open"
  >
    {{ (current?.name || '工').slice(0, 1) }}
  </button>

  <div v-else class="relative">
    <button
      class="flex w-full items-center gap-2 rounded-xl border border-line/70 bg-well/50 px-2.5 py-2 text-left transition-colors duration-200 ease-[var(--ease)] hover:border-line-strong"
      :aria-expanded="open"
      @click.stop="open = !open"
    >
      <span
        class="grid h-6 w-6 shrink-0 place-items-center rounded-lg bg-ink text-[11px] font-semibold text-paper"
      >
        {{ (current?.name || '工').slice(0, 1) }}
      </span>
      <span class="min-w-0 flex-1">
        <span class="block truncate text-[12.5px] font-medium leading-tight">
          {{ current?.name || '工作区' }}
        </span>
        <span class="mono-label mt-0.5 block truncate">
          {{ current?.repos ?? 0 }} 个仓库<template v-if="current?.sources?.length">
            · {{ current!.sources.join(' / ') }}
          </template>
        </span>
      </span>
      <AppIcon name="chevrons-up-down" :size="13" class="shrink-0 text-ink-faint" />
    </button>

    <div
      v-if="open"
      class="absolute left-0 right-0 top-[calc(100%+6px)] z-50 overflow-hidden rounded-xl border border-line bg-panel shadow-pop"
    >
      <p class="mono-label px-3 pb-1 pt-2.5">切换工作区</p>
      <ul class="max-h-[280px] overflow-y-auto pb-1">
        <li v-for="w in items" :key="w.slug">
          <button
            class="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-well/60"
            @click="pick(w.slug)"
          >
            <span class="min-w-0 flex-1">
              <span class="block truncate text-[12.5px]">{{ w.name }}</span>
              <span class="mono-label">{{ w.repos }} 个仓库</span>
            </span>
            <AppIcon
              v-if="w.slug === current?.slug"
              name="check"
              :size="13"
              class="shrink-0 text-ok"
            />
          </button>
        </li>
        <li v-if="!items.length" class="px-3 py-2 text-[12px] text-ink-faint">还没有工作区</li>
      </ul>
    </div>
  </div>
</template>
