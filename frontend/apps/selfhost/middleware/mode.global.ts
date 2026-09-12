// 全局路由门控:页面经 definePageMeta({ modes: [...] }) 声明可见档位,
// 当前部署档位(NUXT_PUBLIC_DEPLOYMENT_MODE,默认 selfhost)不在列表内时重定向。
export default defineNuxtRouteMiddleware((to) => {
  const mode = useRuntimeConfig().public.mode as string
  const modes = to.meta.modes as string[] | undefined

  if (modes?.length && !modes.includes(mode)) {
    return navigateTo('/dashboard', { replace: true })
  }
})
