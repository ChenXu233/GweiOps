// 没有会话就回登录页。首启(库里还没有用户)也走这里——登录页会显示"创建管理员"。
export default defineNuxtRouteMiddleware(async (to) => {
  if (to.path === '/login') return

  // SSR 时也要带上浏览器的 cookie,否则首屏就会被错误地踢回登录页
  const requestFetch = useRequestFetch()
  try {
    const status = await requestFetch<{ needs_setup: boolean; authenticated: boolean }>(
      '/api/auth/status',
    )
    if (status.needs_setup || !status.authenticated) {
      return navigateTo('/login', { replace: true })
    }
  } catch {
    return navigateTo('/login', { replace: true })
  }
})
