<script setup lang="ts">
import { usePluginWidgets } from '@gwei/core/composables/usePluginWidgets'

/**
 * 一个前端扩展槽:按槽位名拉取插件声明的卡片。
 *
 * 槽位清单在引擎侧(engine/plugin_manager/slots.py),插件清单里写错的槽位在加载期
 * 就被拒——所以这里的 slot 一定是核心声明过的名字。拉不到卡片时留一句提示,
 * 不把页面撑成空白。
 */
const props = withDefaults(
  defineProps<{ slot: string, emptyHint?: string, hideEmpty?: boolean }>(),
  { emptyHint: '插件可以往这里放自己的卡片。', hideEmpty: false },
)

const { widgets } = usePluginWidgets(props.slot)
</script>

<template>
  <div class="space-y-4">
    <section v-for="w in widgets" :key="w.plugin + w.title" class="panel overflow-hidden">
      <PluginWidget :widget="w" />
    </section>

    <section
      v-if="!widgets.length && !props.hideEmpty"
      class="rounded-panel border border-dashed border-line bg-panel/40 px-5 py-8 text-center"
    >
      <p class="text-[12px] text-ink-faint">{{ emptyHint }}</p>
    </section>
  </div>
</template>
