// 当前登录的人。侧边栏用它显示"谁在操作",退出也走这里。
export interface AuthUser {
  user_id: string
  name: string
  tenant: string
  permissions: string[]
  is_sub_user: boolean
}

export function useAuth() {
  const user = useState<AuthUser | null>('auth-user', () => null)

  async function load() {
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
    return !!user.value?.permissions.includes(permission)
  }

  return { user, load, logout, can }
}
