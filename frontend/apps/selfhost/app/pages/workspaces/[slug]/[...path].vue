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
import { SCOPED_ROUTE_PARAMS } from '~/composables/useRouteParam'

const route = useRoute()
const router = useRouter()

/** 工作区段之后剩下的那串路径:`/workspaces/acme/issues/7` → `issues/7`。 */
const inner = computed(() => {
  const parts = route.path.split('/').filter(Boolean)
  return parts.slice(2).join('/') || 'issues'
})

// 剩下的路径重新交给路由表解析:命中的那条才是真正的页面,它自己也带着参数
// (`/issues/7` → `{ id: '7' }`)。
const resolved = computed(() => router.resolve('/' + inner.value))

// `defineAsyncComponent` 交给模板:`<component :is>` 会把函数当成渲染函数调,
// 立刻炸。这里包一层,它才知道那是个待加载的组件。
const view = computed(() => {
  // 读 `route.matched` 不行:那里面最靠后的一条是这个文件自己,照它渲染就是无限
  // 递归。
  const last = resolved.value.matched[resolved.value.matched.length - 1]
  const file = last?.components ? Object.values(last.components)[0] : null
  if (!file) return null
  // 路由表里的页面有两种形态:还没加载时是 `() => import(...)`,加载过一次之后就是
  // 组件本身。后者直接渲染 —— 再包一层 defineAsyncComponent 会把它当 options,
  // 报 "loader is not a function"。
  return typeof file === 'function' ? defineAsyncComponent(file as never) : (file as never)
})

// 页面组件是被这里当子组件渲染的:`useRoute()` 里只有 catch-all 自己的参数
// (slug / path),`id`、`name` 这些得从这里传下去,见 `useRouteParam`。
provide(SCOPED_ROUTE_PARAMS, computed(() => resolved.value.params))

if (!view.value) {
  throw createError({ statusCode: 404, statusMessage: '这个工作区里没有这个页面' })
}
</script>

<template>
  <component :is="view" v-if="view" :key="route.path" />
</template>
