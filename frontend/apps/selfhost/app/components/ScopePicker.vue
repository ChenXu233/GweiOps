<script setup lang="ts">
// 范围闸:整个工作区 / 某个项目 / 某个仓库。
//
// 它是一个筛选器,不是一段导航。用户真正的问题始终是"我现在要做什么",仓库
// 是上下文不是目的地 —— 所以这里不放"每个仓库一个入口",只把同一张板子收窄。
import { useRepos } from '@gwei/core/composables/useRepos'
import { useScope } from '@gwei/core/composables/useScope'
import { useWorkspaces } from '@gwei/core/composables/useWorkspaces'

const { project, repo, setScope } = useScope()
const { repos, projects } = useRepos()
const { current } = useWorkspaces()

// 选了仓库时项目档跟着它走:显示的是那一个仓库所属项目的名字。
const activeProject = computed(
  () => project.value || repos.value.find((r) => r.slug === repo.value)?.project || '',
)

const projectOptions = computed(() =>
  projects.value.map((p) => ({ value: p.slug, label: p.name, hint: `${p.repos} 个仓库` })),
)

const repoOptions = computed(() => {
  const rows = activeProject.value
    ? repos.value.filter((r) => r.project === activeProject.value)
    : repos.value
  return rows.map((r) => ({ value: r.slug, label: r.name, hint: sourceLabel(r.source) }))
})

function sourceLabel(source: string) {
  return { github: 'GitHub', cnb: 'CNB', gitlab: 'GitLab' }[source] ?? source
}

function pickProject(value: string) {
  // 换项目就把仓库档清掉:上一档的仓库不一定属于这个项目。
  setScope({ project: value, repo: '' })
}

function pickRepo(value: string) {
  setScope({ repo: value })
}
</script>

<template>
  <div class="flex flex-wrap items-center gap-2">
    <span class="eyebrow shrink-0">范围</span>

    <select
      class="field h-8 max-w-[180px] text-[12.5px]"
      :value="activeProject"
      @change="pickProject(($event.target as HTMLSelectElement).value)"
    >
      <option value="">{{ current?.name ?? '整个工作区' }}</option>
      <option v-for="o in projectOptions" :key="o.value" :value="o.value">
        {{ o.label }} · {{ o.hint }}
      </option>
    </select>

    <select
      class="field h-8 max-w-[200px] text-[12.5px]"
      :value="repo"
      @change="pickRepo(($event.target as HTMLSelectElement).value)"
    >
      <option value="">全部仓库</option>
      <option v-for="o in repoOptions" :key="o.value" :value="o.value">
        {{ o.label }} · {{ o.hint }}
      </option>
    </select>

    <button
      v-if="project || repo"
      class="btn-ghost btn-sm text-[12px]"
      @click="setScope({ project: '', repo: '' })"
    >
      清空
    </button>
  </div>
</template>
