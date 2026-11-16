<script setup lang="ts">
import { usePluginWidgets } from '@gwei/core/composables/usePluginWidgets'
import AgentDock from './AgentDock.vue'

/**
 * 全局悬浮区(`global.dock`):核心只声明"右下角能挂一样东西",挂什么由插件定。
 *
 * 这里不是"渲染一张卡片":助手窗口有输入框、批准卡、事件流,声明式 schema 表达
 * 不了。所以判据是"这个槽归哪个插件",内容由核心里对应的窗口组件提供——
 * 开关仍然由一个事实决定:**插件在不在**。没装就没有窗口,不是装一个空的。
 *
 * 当前只有 `console-agent` 认领这个槽;换成别的插件时在这里加一行映射,
 * 而不是在布局文件里再写死一个组件。
 */
const DOCK_COMPONENTS: Record<string, unknown> = {
  'console-agent': AgentDock,
}

const { widgets } = usePluginWidgets('global.dock')

const dock = computed(() => {
  // 槽里同一时刻只该有一张卡片(引擎侧的单占槽校验),这里取第一张就够
  const owner: string = widgets.value[0]?.plugin ?? ''
  return owner ? (DOCK_COMPONENTS[owner] ?? null) : null
})

const dockComponent = computed(() => dock.value)
</script>

<template>
  <component :is="dockComponent" v-if="dockComponent" />
</template>
