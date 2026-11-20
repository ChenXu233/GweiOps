<script setup lang="ts">
// 工作区管理:把"我是谁、我进得去哪几道账、当前这道账走到哪一步"放在一页。
//
// 工作区是数据边界,不是筛选器。所以这一页不提供跨工作区的汇总数字:每个工作区
// 的仓库数是它自己的;切过去就是换一道账。创建/删除/改名没有对应的引擎接口,
// 这里就不画按钮 —— 画了也只会给人一个点了没反应的控件。
import { scopePath } from '@gwei/core/api/typed'
import type { AuthMembership } from '~/composables/useAuth'

const { items, current, loading, error, refresh, hrefFor } = useWorkspaces()
const { user, load: loadUser } = useAuth()

interface OnboardingStep {
  key: string
  title: string
  done: boolean
  detail: string
  next: string
}
interface Onboarding {
  workspace: string
  complete: boolean
  steps: OnboardingStep[]
}

const onboarding = ref<Onboarding | null>(null)
const onboardingError = ref('')
const onboardingLoading = ref(false)

const membership = computed(() =>
  (user.value?.workspaces ?? []).find((m) => m.workspace === current.value?.slug),
)

const useMock = useRuntimeConfig().public.useMock === true

function onboardingSteps(slug: string): OnboardingStep[] {
  return [
    { key: 'workspace', title: '建工作区', done: true, detail: slug, next: '' },
    { key: 'source', title: '接入一个来源', done: false, detail: '', next: '去「信号源」页填令牌' },
    { key: 'repo', title: '接进一个仓库', done: false, detail: '0 个仓库', next: '去「仓库」页接入' },
    {
      key: 'first-workflow',
      title: '跑通第一条工作流',
      done: false,
      detail: '0 条议题 / 0 条账',
      next: '仓库接进来之后,它已有的议题会被读一次并排进议题板',
    },
  ]
}

// 同一个工作区的进度只读一份:挂载时的 refreshAll 与"当前工作区变化"的 watch
// 会同时要它,合到一次请求上。换了工作区则另起一次,旧答案不再写回。
let onboardingFlight: { slug: string; promise: Promise<void> } | null = null

async function loadOnboarding(): Promise<void> {
  const slug = current.value?.slug
  if (!slug) return
  if (onboardingFlight?.slug === slug) return onboardingFlight.promise
  onboardingLoading.value = true
  onboardingError.value = ''
  // 换工作区时先把上一道账的进度清掉。留着旧数字会让人以为新工作区已经跑通。
  onboarding.value = null
  const run = (async () => {
    try {
      if (useMock) {
        if (current.value?.slug === slug) {
          onboarding.value = { workspace: slug, complete: false, steps: onboardingSteps(slug) }
        }
      } else {
        const data = await $fetch<Onboarding>(
          scopePath('/api/workspaces/{slug}/onboarding').replace('{slug}', encodeURIComponent(slug)),
        )
        // 读的过程中又换了工作区:这一份是上一道账的,不写回。
        if (current.value?.slug === slug) onboarding.value = data
      }
    } catch (e) {
      if (current.value?.slug !== slug) return
      onboarding.value = null
      const err = e as { data?: { detail?: string } }
      onboardingError.value = err.data?.detail || '读不到开通进度'
    } finally {
      // 被新工作区顶替的那一次不能关掉新请求的 loading。
      if (current.value?.slug === slug) onboardingLoading.value = false
    }
  })()
  onboardingFlight = {
    slug,
    promise: run.finally(() => {
      if (onboardingFlight?.slug === slug) onboardingFlight = null
    }),
  }
  return onboardingFlight.promise
}

async function refreshAll() {
  await Promise.allSettled([refresh(), loadUser()])
  await loadOnboarding()
}

/** 列出这个工作区里的角色:一行一个,不把几个工作区的权限并成一份。 */
function roleNames(m?: AuthMembership): string {
  if (!m) return '没有角色'
  return m.roles.map((r) => r.name).join(' / ') || '没有角色'
}

onMounted(async () => {
  await refreshAll()
})

watch(() => current.value?.slug, () => loadOnboarding())
</script>

<template>
  <div class="space-y-5">
    <PageHeader
      eyebrow="WORKSPACES"
      title="工作区"
      :description="`${user?.display_name || '你'}能进的每一道账,以及${current?.name || '当前工作区'}走到哪一步。`"
    >
      <template #actions>
        <button class="btn-outline btn-sm" @click="refreshAll">
          <AppIcon name="refresh" :size="13" />
          刷新
        </button>
      </template>
    </PageHeader>

    <div v-if="error || onboardingError" class="panel border-coral/30 bg-coral/5 p-4 text-[12.5px] text-coral">
      {{ error ? '拉不到工作区列表。确认引擎在跑,或开启 mock 模式。' : onboardingError }}
    </div>

    <!-- 我进得去的工作区:这里是导航,不是汇总面板。切过去就是换一整套账。 -->
    <section class="space-y-3">
      <div class="flex items-baseline gap-2">
        <h2 class="text-[13px] font-semibold">我能进的工作区</h2>
        <span class="text-[11.5px] text-ink-faint">{{ items.length }} 个</span>
      </div>

      <div v-if="loading && !items.length" class="grid gap-3 sm:grid-cols-2">
        <div v-for="i in 4" :key="i" class="h-[112px] skeleton" />
      </div>

      <EmptyState
        v-else-if="!items.length"
        icon="layers"
        title="还没有工作区"
        hint="注册会给你建一个自己的工作区;别人邀请你时,你会多一条成员关系。"
      />

      <div v-else class="grid gap-3 sm:grid-cols-2">
        <NuxtLink
          v-for="w in items"
          :key="w.slug"
          :to="hrefFor('/issues', w.slug)"
          class="panel panel-lift flex items-start gap-3 p-4"
          :class="w.slug === current?.slug ? 'border-ink/25' : ''"
        >
          <span class="grid h-9 w-9 shrink-0 place-items-center rounded-tile bg-well text-[12px] font-semibold">
            {{ (w.name || '工').slice(0, 1) }}
          </span>
          <span class="min-w-0 flex-1">
            <span class="flex items-center gap-2">
              <span class="truncate text-[13px] font-medium">{{ w.name }}</span>
              <span v-if="w.slug === current?.slug" class="chip chip-ok">当前</span>
            </span>
            <span class="mono-label mt-1 block truncate">{{ w.slug }}</span>
            <span class="mt-2 block text-[11.5px] text-ink-soft">
              {{ w.repos }} 个仓库<template v-if="w.sources?.length"> · {{ w.sources.join(' / ') }}</template>
            </span>
          </span>
          <AppIcon name="arrow-up-right" :size="14" class="mt-0.5 shrink-0 text-ink-faint" />
        </NuxtLink>
      </div>
    </section>

    <!-- 当前工作区:我在这里的身份 + 这道账的开通进度。不把别的工作区的角色混进来。 -->
    <template v-if="current">
      <section class="grid gap-3 sm:grid-cols-3">
        <div class="panel p-4">
          <p class="mono-label">我的角色</p>
          <p class="mt-2 text-[13px] font-medium">{{ roleNames(membership) }}</p>
          <p class="mt-1 text-[11.5px] text-ink-faint">只在 {{ current.name }} 里算数</p>
        </div>
        <div class="panel p-4">
          <p class="mono-label">仓库</p>
          <p class="num mt-2 text-[22px] font-semibold leading-none">{{ current.repos ?? 0 }}</p>
          <p class="mt-1 text-[11.5px] text-ink-faint">接进这道账的那几份代码</p>
        </div>
        <div class="panel p-4">
          <p class="mono-label">开通</p>
          <p class="mt-2 text-[13px] font-medium">
            {{ onboardingLoading && !onboarding ? '读进度…' : onboarding?.complete ? '已经跑通' : '还差几步' }}
          </p>
          <p class="mt-1 text-[11.5px] text-ink-faint">从来源到第一条工作流</p>
        </div>
      </section>

      <section class="panel overflow-hidden">
        <div class="flex items-center justify-between border-b border-line/70 px-5 py-3.5">
          <h2 class="text-[13px] font-semibold">开通进度</h2>
          <span class="eyebrow">{{ onboarding?.steps?.filter((s) => s.done).length ?? 0 }} / {{ onboarding?.steps?.length ?? 4 }}</span>
        </div>

        <ol v-if="onboarding?.steps?.length" class="divide-y divide-line/60">
          <li v-for="step in onboarding.steps" :key="step.key" class="flex items-start gap-3 px-5 py-3.5">
            <span
              class="grid h-6 w-6 shrink-0 place-items-center rounded-full border"
              :class="step.done ? 'border-ok/40 bg-ok/10 text-ok' : 'border-line text-ink-faint'"
            >
              <AppIcon :name="step.done ? 'check' : 'dot-circle'" :size="13" />
            </span>
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-baseline gap-2">
                <span class="text-[12.5px] font-medium">{{ step.title }}</span>
                <span v-if="step.detail" class="text-[11.5px] text-ink-faint">{{ step.detail }}</span>
              </div>
              <p v-if="step.next && !step.done" class="mt-1 text-[11.5px] leading-relaxed text-ink-soft">
                {{ step.next }}
              </p>
            </div>
          </li>
        </ol>
        <div v-else class="px-5 py-8 text-center text-[12px] text-ink-faint">
          {{ onboardingLoading ? '正在读进度…' : '这个工作区的开通进度读不到' }}
        </div>
      </section>

      <section class="flex flex-wrap items-center gap-2">
        <NuxtLink class="btn-outline btn-sm" :to="hrefFor('/repos')">
          <AppIcon name="repos" :size="13" />
          仓库
        </NuxtLink>
        <NuxtLink class="btn-outline btn-sm" :to="hrefFor('/signals')">
          <AppIcon name="radio" :size="13" />
          信号源
        </NuxtLink>
        <NuxtLink class="btn-outline btn-sm" :to="hrefFor('/team')">
          <AppIcon name="users" :size="13" />
          成员
        </NuxtLink>
        <NuxtLink class="btn-outline btn-sm" :to="hrefFor('/settings')">
          <AppIcon name="settings" :size="13" />
          设置
        </NuxtLink>
      </section>
    </template>
  </div>
</template>
