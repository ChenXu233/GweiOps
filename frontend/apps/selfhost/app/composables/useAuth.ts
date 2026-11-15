// 当前登录的人。侧边栏用它显示"谁在操作",退出也走这里。
export interface AuthUser {
  user_id: string
  name: string
  tenant: string
  permissions: string[]
  is_sub_user: boolean
}

// 演示模式没有引擎,也就没有身份:/api/auth/me 一定 401。若照实处理,页面上
// 所有写操作都会消失,只能看到半张界面。这里给一个只活在演示里的身份;它同时
// 是服务端与客户端的初始值,否则首屏会和服务端渲染的对不上。
const DEMO_USER: AuthUser = {
  user_id: 'demo',
  name: '演示身份',
  tenant: 'default',
  permissions: [],
  is_sub_user: false,
}

export function useAuth() {
  const useMock = useRuntimeConfig().public.useMock === true
  const user = useState<AuthUser | null>('auth-user', () => (useMock ? DEMO_USER : null))

  async function load() {
    if (useMock) return user.value
    try {
      const res = await $fetch<{ user: AuthUser }>('/api/auth/me')
      user.value = res.user
    } catch {
      user.value = null
    }
    return user.value
  }

  async function logout() {
    await $fetch('/api/auth/logout', { method: 'POST' }).catch(() => undefined)
    user.value = null
    await navigateTo('/login', { replace: true })
  }

  function can(permission: string) {
    if (useMock) return true
    return !!user.value?.permissions.includes(permission)
  }

  return { user, load, logout, can }
}