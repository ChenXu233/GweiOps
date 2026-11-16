<script setup lang="ts">
import { useRepoList } from '@gwei/core/composables/useRepoList'

const { plugins, enabledCount, loading, error, actionError, toggling, setEnabled, rescan } =
  useRepoList()

const { can } = useAuth()
const canManage = computed(() => can('plugins.write'))

function forgot(reason: string): string {
  return reason || '未启用'
}
</script>

<template>
  <div class="space-y-5">
    <PageHeader
      eyebrow="PLUGINS"
      title="插件"
      description="引擎只负责编排，监控、金丝雀、通知都由插件提供。"
    >
      <template #actions>
        <div class="flex items-center gap-3">
          <span class="eyebrow">{{ enabledCount }} / {{ plugins.length }} 已启用</span>
          <button
            class="btn-ghost inline-flex items-center gap-1.5 text-[12px]"
            :disabled="!canManage || toggling === '*'"
            :title="canManage ? '重新扫描插件目录' : '需要 plugins.write 权限'"
            @click="rescan"
          >
            <AppIcon name="refresh" :size="13" :class="toggling === '*' ? 'animate-spin' : ''" />
            {{ toggling === '*' ? '扫描中…' : '重扫描' }}
          </button>
        </div>
      </template>
    </PageHeader>

    <div class="flex items-start gap-3 rounded-panel border border-line bg-well/50 px-5 py-4">
      <AppIcon name="shield-check" :size="15" class="mt-0.5 text-ink-faint" />
      <p class="text-[12px] leading-relaxed text-ink-soft">
        <span class="font-medium text-ink">发现不等于启用。</span>
        装进插件目录、能解析出能力，都不代表它会在流程里被执行——只有被显式打开、且声明了对应效果单元的插件才会真正动手。
      </p>
    </div>

    <div v-if="error" class="panel border-coral/30 bg-coral/5 p-4 text-[12.5px] text-coral">
      拉不到插件清单。确认引擎在跑，或开启 mock 模式。
    </div>

    <div
      v-if="actionError"
      class="panel border-coral/30 bg-coral/5 p-4 text-[12.5px] text-coral"
    >
      {{ actionError }}
    </div>

    <div v-if="loading && !plugins.length" class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <div v-for="i in 6" :key="i" class="h-[210px] skeleton" />
    </div>

    <EmptyState
      v-else-if="!plugins.length"
      icon="plugins"
      title="插件目录是空的"
      hint="把 manifest v2 插件放进 plugins/ 目录，重启后即可被发现。"
    />

    <div v-else class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <article
        v-for="plugin in plugins"
        :key="plugin.id"
        class="panel panel-lift flex flex-col p-5"
      >
        <div class="flex items-start justify-between gap-3">
          <span
            class="grid h-9 w-9 place-items-center rounded-tile bg-well text-ink-soft transition-colors duration-200 ease-[var(--ease)]"
          >
            <AppIcon :name="plugin.enabled ? 'plugins' : 'box'" :size="16" />
          </span>
          <span
            class="chip"
            :class="plugin.error ? 'chip-warn' : plugin.enabled ? 'chip-ok' : ''"
            :title="plugin.error || plugin.reason"
          >
            {{ plugin.error ? '起不来' : plugin.enabled ? '已启用' : '未启用' }}
          </span>
        </div>

        <h2 class="mt-4 font-mono text-[13px] font-medium">{{ plugin.name }}</h2>
        <p class="mt-1.5 line-clamp-3 text-[12px] leading-relaxed text-ink-soft">
          {{ plugin.description }}
        </p>

        <p v-if="plugin.error" class="mt-2 font-mono text-[11px] text-coral">
          {{ plugin.error }}
        </p>
        <p v-else-if="!plugin.enabled" class="mt-2 font-mono text-[11px] text-ink-faint">
          {{ forgot(plugin.reason) }}
        </p>
        <p v-else-if="plugin.instances.length" class="mt-2 font-mono text-[11px] text-ink-faint">
          实例 {{ plugin.instances.join(', ') }}
        </p>

        <div class="mt-3 flex flex-wrap gap-1">
          <span
            v-for="cap in plugin.capabilities.slice(0, 3)"
            :key="cap"
            class="rounded bg-well px-1.5 py-0.5 font-mono text-[10.5px] text-ink-faint"
          >
            {{ cap }}
          </span>
          <span
            v-if="plugin.capabilities.length > 3"
            class="px-1 font-mono text-[10.5px] text-ink-faint"
          >
            +{{ plugin.capabilities.length - 3 }}
          </span>
        </div>

        <div class="mt-auto flex items-center justify-between border-t border-line/70 pt-3.5">
          <NuxtLink
            v-if="plugin.pageTitle"
            :to="'/plugins/' + encodeURIComponent(plugin.id)"
            class="inline-flex items-center gap-1 text-[12px] font-medium text-ink-soft transition-colors hover:text-ink"
          >
            打开页面
            <AppIcon name="external-link" :size="12" />
          </NuxtLink>
          <span v-else class="font-mono text-[11px] text-ink-faint">v{{ plugin.version }}</span>

          <button
            class="inline-flex items-center gap-1.5 rounded border border-line px-2.5 py-1 text-[11.5px] font-medium transition-colors hover:border-ink/40 disabled:opacity-40"
            :disabled="!canManage || toggling === plugin.id"
            :title="canManage ? '' : '需要 plugins.write 权限'"
            @click="setEnabled(plugin.id, !plugin.enabled)"
          >
            {{ toggling === plugin.id ? '…' : plugin.enabled ? '停用' : '启用' }}
          </button>
        </div>
      </article>
    </div>
  </div>
</template>
