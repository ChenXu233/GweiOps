<script setup lang="ts">
import { useRepoList } from '@gwei/core/composables/useRepoList'

const { plugins, loading, error } = useRepoList()

const installedCount = computed(() => plugins.value.filter(p => p.installed).length)
</script>

<template>
  <div class="space-y-4">
    <header class="flex flex-wrap items-end justify-between gap-3">
      <div>
        <div class="mono-label">PLUGINS</div>
        <h1 class="mt-1.5 text-[27px] font-semibold leading-none tracking-tightest">插件</h1>
        <p class="mt-2 text-[12.5px] text-ink-soft">
          引擎只负责编排,监控、金丝雀、通知都由插件提供。
        </p>
      </div>
      <span class="mono-label">{{ installedCount }} / {{ plugins.length }} 已启用</span>
    </header>

    <!-- 发现 ≠ 启用 -->
    <div class="flex items-start gap-3 rounded-panel border border-line bg-well/50 px-5 py-4">
      <AppIcon name="shield-check" :size="15" class="mt-0.5 text-ink-faint" />
      <p class="text-[12px] leading-relaxed text-ink-soft">
        <span class="font-medium text-ink">发现不等于启用。</span>
        装进插件目录、能解析出能力,都不代表它会在流程里被执行——只有被显式打开、且声明了对应效果单元的插件才会真正动手。
      </p>
    </div>

    <div v-if="error" class="card border-coral/30 bg-coral/5 p-4 text-[12.5px] text-coral">
      拉不到插件清单。确认引擎在跑,或开启 mock 模式。
    </div>

    <div v-if="loading && !plugins.length" class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <div v-for="i in 6" :key="i" class="h-[210px] animate-pulse rounded-panel bg-well/60" />
    </div>

    <EmptyState
      v-else-if="!plugins.length"
      icon="plugins"
      title="插件目录是空的"
      hint="把 manifest v2 插件放进 plugins/ 目录,重启后即可被发现。"
    />

    <div v-else class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <article
        v-for="plugin in plugins"
        :key="plugin.id"
        class="group flex flex-col rounded-panel border border-line bg-panel p-5 transition-colors hover:border-ink/20"
      >
        <div class="flex items-start justify-between gap-3">
          <span class="grid h-9 w-9 place-items-center rounded-xl bg-well text-ink-soft transition-colors group-hover:bg-ink group-hover:text-paper">
            <AppIcon :name="plugin.installed ? 'plugins' : 'box'" :size="16" />
          </span>
          <span
            class="rounded-full border px-2 py-0.5 text-[10.5px] font-medium"
            :class="plugin.installed
              ? 'border-ok/25 bg-ok/10 text-ok'
              : 'border-line bg-well text-ink-faint'"
          >
            {{ plugin.installed ? '已启用' : '未启用' }}
          </span>
        </div>

        <h2 class="mt-4 font-mono text-[13px] font-medium">{{ plugin.name }}</h2>
        <p class="mt-1.5 line-clamp-3 text-[12px] leading-relaxed text-ink-soft">
          {{ plugin.description }}
        </p>

        <div class="mt-auto flex items-center justify-between border-t border-line/70 pt-3.5">
          <span class="font-mono text-[10.5px] text-ink-faint">
            {{ plugin.author === 'official' ? '官方' : '社区' }}
            <template v-if="plugin.price !== null"> · ¥{{ plugin.price }}</template>
          </span>

          <NuxtLink
            v-if="plugin.pageTitle"
            :to="'/plugins/' + encodeURIComponent(plugin.id)"
            class="inline-flex items-center gap-1 text-[11.5px] font-medium text-ink-soft transition-colors hover:text-ink"
          >
            打开页面
            <AppIcon name="external-link" :size="12" />
          </NuxtLink>
          <span v-else class="text-[11.5px] text-ink-faint">无页面</span>
        </div>
      </article>
    </div>
  </div>
</template>
