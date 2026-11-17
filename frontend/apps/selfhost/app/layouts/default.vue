<script setup lang="ts">
// 界面路由的前缀:`/workspaces/{slug}/issues`。
//
// 工作区是一个资源,资源要有 URL —— 所以它出现在路径里,而不是 cookie 里。
// 后端那一侧同理(`/api/workspaces/{slug}/…`),两边对齐,分享出去的链接才
// 自带"这是哪一道账"。
//
// 一个只属于一个工作区的人不必每条链接都带那一段:不带也能打开,引擎按他最早的
// 那条成员关系回答。
const route = useRoute()

// `useWorkspaces` 里那份是同一张表:列表、当前选中、以及把工作区补进接口路径
// 的读法都在那儿,这里只是把路由那一段抄进去。
const { current, syncFromRoute } = useWorkspaces()

const scoped = computed(() => {
  const parts = route.path.split('/').filter(Boolean)
  return parts[0] === 'workspaces' && Boolean(parts[1])
})

// 状态跟着路由走:路由里那段是唯一真相源,别处只读它。
watch(
  () => route.fullPath,
  () => syncFromRoute(),
  { immediate: true },
)

onMounted(async () => {
  // 首屏落在默认工作区时,把地址也换成带那一段的:刷新、收藏、分享都是同一道账。
  // 只在挂载后做一次 —— 放在路由钩子里会和服务端渲染的地址打架。
  if (scoped.value || !current.value?.slug) return
  const parts = route.path.split('/').filter(Boolean)
  const rest = parts.length ? `/${parts.join('/')}` : '/issues'
  await navigateTo(`/workspaces/${current.value.slug}${rest}`, { replace: true })
})
</script>

<template>
  <div class="min-h-screen bg-paper text-ink">
    <slot />
  </div>
</template>
