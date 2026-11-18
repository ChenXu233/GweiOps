<script setup lang="ts">
// 一个仓库:它的议题、它的发布管道、它属于哪个项目。
//
// 这是"仓库作为目的地"唯一成立的地方 —— 从一个仓库卡片点进来。范围闸上的
// 仓库档仍然只是筛选,不改导航:用户真正的问题始终是"我现在要做什么"。
import { useRepos } from '@gwei/core/composables/useRepos'
import { useAuth } from '~/composables/useAuth'
import { useWorkspaces } from '@gwei/core/composables/useWorkspaces'

const route = useRoute()
const { hrefFor: scopedTo } = useWorkspaces()
const { repos, loading } = useRepos()
const { can } = useAuth()

const repoId = computed(() => String(route.params.id ?? ''))
const repo = computed(() => repos.value.find((r) => r.id === repoId.value) ?? null)

// 写发布配置要 settings.write:界面只是提前把按钮关掉,拦还是引擎拦。
const canWrite = computed(() => can('settings.write'))

const sourceLabel: Record<string, string> = {
  github: 'GitHub',
  cnb: 'CNB',
  gitlab: 'GitLab',
}
</script>

<template>
  <div class="space-y-5">
    <PageHeader
      :eyebrow="sourceLabel[repo?.source ?? ''] ?? 'REPOSITORY'"
      :title="repo?.name || '仓库'"
      :description="
        repo
          ? `属于项目 ${repo.projectName || '（未归入）'} · ${repo.issueCount} 条议题`
          : loading
            ? '正在读这个仓库…'
            : '这个工作区里没有这个仓库。'
      "
    >
      <template #actions>
        <NuxtLink v-if="repo" :to="scopedTo(`/issues?repo=${encodeURIComponent(repo.slug)}`)" class="btn-outline btn-sm">
          只看它的议题
        </NuxtLink>
        <NuxtLink :to="scopedTo('/repos')" class="btn-ghost btn-sm">返回仓库</NuxtLink>
      </template>
    </PageHeader>

    <template v-if="repo">
      <section class="panel overflow-hidden">
        <div class="flex items-center gap-2 border-b border-line px-5 py-3.5">
          <AppIcon name="repos" :size="14" class="text-ink-faint" />
          <h2 class="text-[13px] font-semibold">身份</h2>
        </div>
        <dl class="grid gap-x-6 gap-y-2 px-5 py-4 sm:grid-cols-3">
          <div>
            <dt class="eyebrow">来源</dt>
            <dd class="mt-1 font-mono text-[12px]">{{ sourceLabel[repo.source] ?? repo.source }}</dd>
          </div>
          <div>
            <dt class="eyebrow">全名</dt>
            <dd class="mt-1 break-all font-mono text-[12px]">{{ repo.name }}</dd>
          </div>
          <div>
            <dt class="eyebrow">在这棵树上的名字</dt>
            <dd class="mt-1 break-all font-mono text-[12px]">{{ repo.slug }}</dd>
          </div>
        </dl>
        <p class="border-t border-line/60 px-5 py-3 text-[11.5px] leading-relaxed text-ink-faint">
          同一个仓库名在两个来源上是两份不同的代码，所以身份是「来源 + 仓库全名」，
          而不是平台给的那个数字 id。
        </p>
      </section>

      <RepoReleasePanel :repo="repo.name" :can-write="canWrite" />
    </template>

    <div v-else-if="!loading" class="panel p-6">
      <p class="text-[13px] font-medium">没有这个仓库</p>
      <p class="mt-1 text-[12px] text-ink-soft">
        它可能属于另一个工作区。先在侧边栏最上面切换工作区，或者回到仓库列表。
      </p>
    </div>
  </div>
</template>
