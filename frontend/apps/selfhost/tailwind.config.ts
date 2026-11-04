import type { Config } from 'tailwindcss'

/**
 * 颜色令牌全部走 CSS 变量(见 assets/css/main.css),组件只写语义名。
 * 形如 rgb(var(--x) / <alpha-value>) 才能用 bg-panel/70 这类透明度修饰符。
 */
export default <Partial<Config>>{
  darkMode: ['class'],
  content: [
    './app.vue',
    './layouts/**/*.vue',
    './pages/**/*.vue',
    './components/**/*.vue',
    '../../packages/core/components/**/*.vue',
  ],
  theme: {
    extend: {
      colors: {
        paper: 'rgb(var(--paper) / <alpha-value>)',
        panel: 'rgb(var(--panel) / <alpha-value>)',
        well: 'rgb(var(--well) / <alpha-value>)',
        solid: 'rgb(var(--solid) / <alpha-value>)',
        'solid-ink': 'rgb(var(--solid-ink) / <alpha-value>)',
        ink: {
          DEFAULT: 'rgb(var(--ink) / <alpha-value>)',
          soft: 'rgb(var(--ink-soft) / <alpha-value>)',
          faint: 'rgb(var(--ink-faint) / <alpha-value>)',
        },
        line: {
          DEFAULT: 'rgb(var(--line) / <alpha-value>)',
          soft: 'rgb(var(--line-soft) / <alpha-value>)',
        },
        brand: 'rgb(var(--brand) / <alpha-value>)',
        lime: {
          DEFAULT: 'rgb(var(--lime) / <alpha-value>)',
          ink: 'rgb(var(--lime-ink) / <alpha-value>)',
        },
        amber: 'rgb(var(--amber) / <alpha-value>)',
        coral: 'rgb(var(--coral) / <alpha-value>)',
        ok: 'rgb(var(--ok) / <alpha-value>)',
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'sans-serif'],
        mono: ['JetBrains Mono', 'SFMono-Regular', 'SF Mono', 'ui-monospace', 'Menlo', 'Consolas', 'monospace'],
      },
      letterSpacing: { tightest: '-0.035em' },
      borderRadius: { panel: '20px' },
      keyframes: {
        rise: { '0%': { opacity: '0', transform: 'translateY(6px)' }, '100%': { opacity: '1', transform: 'translateY(0)' } },
        fade: { '0%': { opacity: '0' }, '100%': { opacity: '1' } },
        slide: { '0%': { opacity: '0', transform: 'translateX(24px)' }, '100%': { opacity: '1', transform: 'translateX(0)' } },
      },
      animation: {
        rise: 'rise .32s cubic-bezier(.22,.68,0,1) both',
        fade: 'fade .2s ease both',
        slide: 'slide .28s cubic-bezier(.22,.68,0,1) both',
      },
    },
  },
  plugins: [],
}
