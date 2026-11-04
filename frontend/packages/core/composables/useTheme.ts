// 主题:light / dark / system。首帧由 nuxt.config 的内联脚本决定,这里只做后续切换。
export type ThemeMode = 'light' | 'dark' | 'system'

const STORAGE_KEY = 'gwei-theme'

export function useTheme() {
  const mode = useState<ThemeMode>('gwei-theme-mode', () => 'system')
  const dark = useState<boolean>('gwei-theme-dark', () => false)

  function apply(next: ThemeMode) {
    if (!import.meta.client) return
    const prefers = window.matchMedia('(prefers-color-scheme: dark)').matches
    const isDark = next === 'dark' || (next === 'system' && prefers)
    const el = document.documentElement
    el.classList.toggle('dark', isDark)
    el.style.colorScheme = isDark ? 'dark' : 'light'
    dark.value = isDark
  }

  function set(next: ThemeMode) {
    mode.value = next
    if (!import.meta.client) return
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // 隐私模式下 localStorage 可能不可写,主题退化为会话内
    }
    apply(next)
  }

  function init() {
    if (!import.meta.client) return
    let stored: ThemeMode = 'system'
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      if (raw === 'light' || raw === 'dark' || raw === 'system') stored = raw
    } catch {
      // 读不到就用系统偏好
    }
    mode.value = stored
    apply(stored)

    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => {
      if (mode.value === 'system') apply('system')
    }
    mq.addEventListener('change', onChange)
    onUnmounted(() => mq.removeEventListener('change', onChange))
  }

  return { mode, dark, set, init }
}
