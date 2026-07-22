<script setup lang="ts">
import { useRepoList } from '@gwei/core/composables/useRepoList'

const { plugins, loading } = useRepoList()
</script>

<template>
  <div class="space-y-6">
    <h1 class="text-2xl font-bold tracking-tight">插件市场</h1>

    <!-- Skeleton loader -->
    <div
      v-if="loading"
      class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-px bg-border rounded-lg overflow-hidden"
    >
      <div v-for="i in 6" :key="i" class="h-48 bg-card animate-pulse" />
    </div>

    <!-- Plugin cards -->
    <div
      v-else
      class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-px bg-border rounded-lg overflow-hidden"
    >
      <div
        v-for="plugin in plugins"
        :key="plugin.id"
        class="bg-card p-5 flex flex-col"
      >
        <div class="text-2xl mb-3">{{ plugin.icon }}</div>
        <div class="text-sm font-semibold mb-1">{{ plugin.name }}</div>
        <p class="text-xs text-muted-foreground leading-relaxed mb-3 flex-1">
          {{ plugin.description }}
        </p>
        <div class="flex items-center justify-between">
          <span class="text-[11px] text-muted-foreground">
            {{ plugin.author === 'official' ? '官方' : '社区' }}
            <template v-if="plugin.price !== null"> · ${{ plugin.price }}/月</template>
            <template v-else> · 免费</template>
          </span>
          <Button
            :class="[
              'text-[11px] h-7 px-3',
              plugin.installed
                ? 'border border-green-500/30 text-green-500 bg-background shadow-sm hover:bg-green-500/10 hover:text-green-500'
                : '',
            ]"
          >
            {{ plugin.installed ? '已安装' : '安装' }}
          </Button>
        </div>
      </div>
    </div>
  </div>
</template>
