<script setup lang="ts">
// 界面路由里的工作区段。
//
// 工作区是资源,资源要有 URL:`/workspaces/{slug}/issues` 才说得清"这是哪一道账"。
// 这个文件本身不画任何东西 —— 它是那一段的落点:地址里有工作区时,按后面的
// `issues`、`repos`、`settings` 去找同名页面挂上。
//
// 为什么不给每个页面复制一份壳:页面文件在 `pages/` 下只有一份,`<NuxtPage>` 读的
// 也是那一份。再复制一份就变成两份实现,迟早一边改了另一边没改。这里只复用。
//
// 页面从路由表里取,而不是把每页的路径抄成一张映射表:后者是第二个真相源,加一个
// 页面就会漏一个。取不到页面 = 地址写错了,交回 Nuxt 的 404。
const route = useRoute()
const router = useRouter()

/** 工作区段之后剩下的那串路径:`/workspaces/acme/issues/7` → `issues/7`。 */
const inner = computed(() => {
  const parts = route.path.split('/').filter(Boolean)
  return parts.slice(2).join('/') || 'issues'
})

// `defineAsyncComponent` 交给模板:`<component :is>` 会把函数当成渲染函数调,
// 立刻炸。这里包一层,它才知道那是个待加载的组件。
const view = computed(() => {
  // 读 `route.matched` 不行:那里面最靠后的一条是这个文件自己,照它渲染就是无限
  // 递归。把剩下的路径重新交给路由表解析,拿到的才是真正的那个页面。
  const resolved = router.resolve('/' + inner.value)
  const last = resolved.matched[resolved.matched.length - 1]
  const file = last?.components ? Object.values(last.components)[0] : null
  return file ? defineAsyncComponent(file as never) : null
})

if (!view.value) {
  throw createError({ statusCode: 404, statusMessage: '这个工作区里没有这个页面' })
}
</script>

<template>
  <component :is="view" v-if="view" :key="inner" />
</template>
