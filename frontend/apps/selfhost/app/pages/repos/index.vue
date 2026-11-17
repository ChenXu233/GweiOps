<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ReposApi } from '@gwei/core/api/client'
import { useRepoList } from '@gwei/core/composables/useRepoList'
import { useWorkspaces } from '@gwei/core/composables/useWorkspaces'

const { repos, loading, error, refresh } = useRepoList()
// 仓库属于一个工作区:同一个仓库名在别的平台上不是同一份代码,所以列表上带来源。
const { current } = useWorkspaces()

// 按项目分组,但不给项目单独一条导航:项目是范围,不是目的地。
const grouped = computed(() => {
  const byProject = new Map<string, { name: string; rows: typeof repos.value }>()
  for (const repo of repos.value) {
    const key = repo.project || ''
    const bucket = byProject.get(key) ?? { name: repo.projectName || '未归入项目', rows: [] }
    bucket.rows.push(repo)
    byProject.set(key, bucket)
  }
  return [...byProject.entries()].map(([slug, v]) => ({ slug, ...v }))
})

const sourceLabel: Record<string, string> = {
  github: 'GitHub',
  cnb: 'CNB',
  gitlab: 'GitLab',
}

const statusTone: Record<string, 'ok' | 'warn' | 'idle'> = {
  running: 'ok',
  configuring: 'warn',
  paused: 'idle',
}

const statusLabel: Record<string, string> = {
  running: '在跑',
  configuring: '配置中',
  paused: '已暂停',
}

const statusChip: Record<string, string> = {
  running: 'chip-ok',
  configuring: 'chip-warn',
  paused: '',
}

// 接入表单。仓库是**接**进来的:投递只会喂已接入的仓库,没接入的来源连工作流
// 都不起。所以这一页必须能接、能解绑,而不是只列一张已经接好的表。
const useMock = useRuntimeConfig().public.useMock === true
const sources = ref<{ source: string; label: string }[]>([])
const pickedSource = ref('')
const fullName = ref('')
const formError = ref('')
const formNote = ref('')
const busy = ref(false)

async function loadSources() {
  if (useMock) {
    sources.value = [
      { source: 'github', label: 'GitHub' },
      { source: 'gitlab', label: 'GitLab' },
      { source: 'cnb', label: 'CNB' },
    ]
    pickedSource.value = 'github'
    return
  }
  try {
    sources.value = await ReposApi.sources()
    pickedSource.value = pickedSource.value || sources.value[0]?.source || ''
  } catch {
    // 拉不到来源就说不清"能接什么",表单留着让人重试,不猜一张默认表
    sources.value = []
  }
}

async function submit() {
  formError.value = ''
  formNote.value = ''
  if (!pickedSource.value) {
    formError.value = '先选一个来源'
    return
  }
  busy.value = true
  try {
    const result = await ReposApi.connect(pickedSource.value, fullName.value)
    formNote.value = result.created
      ? `已接入 ${result.name}。第一次投递到达时它才会开始管议题。`
      : `${result.name} 早就在这个工作区里了,这次没有改动。`
    fullName.value = ''
    await refresh()
  } catch (e) {
    formError.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}

const removing = ref('')
async function disconnect(repo: { slug: string; source: string; name: string }) {
  removing.value = repo.slug
  formError.value = ''
  try {
    // slug 不可逆,解绑要的是"来源 + 全名":这两栏仓库行上都有
    await ReposApi.disconnect(repo.source, repo.name)
    await refresh()
  } catch (e) {
    formError.value = e instanceof Error ? e.message : String(e)
  } finally {
    removing.value = ''
  }
}

onMounted(loadSources)
</script>

<template>
  <div class="space-y-5">
    <PageHeader
      eyebrow="REPOSITORIES"
      title="仓库"
      :description="`${current?.name ?? '当前工作区'}里引擎订阅的仓库，以及它当前盯着的执行体数量。`"
    >
      <template #actions>
        <button class="btn-outline btn-sm" :disabled="loading" @click="refresh">
          <AppIcon name="refresh" :size="13" :class="loading ? 'animate-spin' : ''" />
          刷新
        </button>
      </template>
    </PageHeader>

    <div v-if="error" class="panel border-coral/30 bg-coral/5 p-4 text-[12.5px] text-coral">
      拉不到仓库列表。确认引擎在跑，或开启 mock 模式。
    </div>

    <!-- 接入:这一步之前投递一律不处理,所以它排在最上面 -->
    <section class="panel space-y-3 p-5">
      <div class="flex flex-wrap items-baseline gap-2">
        <h2 class="text-[13px] font-semibold">接入一个仓库</h2>
        <span class="text-[11.5px] text-ink-faint">
          接入之前，这个仓库的投递不会被处理：拉代码、跑模型都从第一次投递开始
        </span>
      </div>

      <form class="flex flex-wrap items-start gap-2" @submit.prevent="submit">
        <select v-model="pickedSource" class="field h-9 w-[140px] text-[12.5px]" :disabled="busy">
          <option v-if="!sources.length" value="">没有可用的来源</option>
          <option v-for="s in sources" :key="s.source" :value="s.source">
            {{ s.label || s.source }}
          </option>
        </select>
        <input
          v-model.trim="fullName"
          class="field h-9 min-w-[220px] flex-1 font-mono text-[12.5px]"
          placeholder="所有者/仓库名，例如 acme/api"
          :disabled="busy"
        />
        <button class="btn-outline btn-sm h-9" type="submit" :disabled="busy || !sources.length">
          {{ busy ? '接入中…' : '接入' }}
        </button>
      </form>

      <p v-if="formError" class="text-[12px] text-coral">{{ formError }}</p>
      <p v-if="formNote" class="text-[12px] text-ink-soft">{{ formNote }}</p>
    </section>

    <div v-if="loading && !repos.length" class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <div v-for="i in 6" :key="i" class="h-[186px] skeleton" />
    </div>

    <EmptyState
      v-else-if="!repos.length"
      icon="repos"
      title="还没有接入仓库"
      hint="在上面填一个仓库全名接入它。装一个来源适配器，那一家的仓库才接得进来。"
    />

    <!-- 按项目分组:项目是范围不是目的地,所以是分组标题,不是一级导航 -->
    <template v-else>
      <section v-for="group in grouped" :key="group.slug" class="space-y-3">
        <div class="flex items-baseline gap-2">
          <h2 class="text-[13px] font-semibold">{{ group.name }}</h2>
          <span class="font-mono text-[11.5px] text-ink-faint">{{ group.rows.length }} 个仓库</span>
          <NuxtLink
            v-if="group.slug"
            :to="`/issues?project=${encodeURIComponent(group.slug)}`"
            class="ml-auto text-[11.5px] text-ink-soft hover:underline"
          >
            只看这个项目的议题
          </NuxtLink>
        </div>

        <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <NuxtLink
            v-for="repo in group.rows"
            :key="repo.id"
            :to="`/repos/${encodeURIComponent(repo.id)}`"
            class="panel panel-lift group flex flex-col p-5"
          >
            <div class="flex items-start justify-between gap-3">
              <span
                class="grid h-9 w-9 place-items-center rounded-tile bg-well text-ink-soft transition-colors duration-200 ease-[var(--ease)] group-hover:bg-ink group-hover:text-paper"
              >
                <AppIcon name="repos" :size="16" />
              </span>
              <StatusPip :tone="statusTone[repo.status]" :label="statusLabel[repo.status]" />
            </div>

            <div class="mt-4 flex items-baseline gap-2">
              <h3 class="min-w-0 break-all font-mono text-[13px] font-medium leading-snug">{{ repo.name }}</h3>
              <span class="shrink-0 rounded-md bg-well px-1.5 py-0.5 text-[10.5px] text-ink-faint">
                {{ sourceLabel[repo.source] ?? repo.source }}
              </span>
            </div>

            <div class="mt-auto grid grid-cols-2 gap-3 border-t border-line/70 pt-3.5">
              <div>
                <div class="eyebrow">议题</div>
                <div class="num mt-1 text-[15px] font-semibold">{{ repo.issueCount }}</div>
              </div>
              <div>
                <div class="eyebrow">执行体</div>
                <div class="num mt-1 text-[15px] font-semibold">{{ repo.activeAgents }}</div>
              </div>
            </div>

            <div class="mt-3 flex items-center gap-2">
              <span class="font-mono text-[11.5px] text-ink-faint">同步于 {{ repo.lastSyncAt }}</span>
              <button
                class="ml-auto text-[11.5px] text-ink-soft hover:text-coral"
                type="button"
                :disabled="removing === repo.slug"
                @click.prevent="disconnect(repo)"
              >
                {{ removing === repo.slug ? '解绑中…' : '解除接入' }}
              </button>
            </div>
          </NuxtLink>
        </div>
      </section>
    </template>
  </div>
</template>