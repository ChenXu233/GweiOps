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
    './composables/**/*.vue',
    '../../packages/core/components/**/*.vue',
  ],
  theme: {
    extend: {
      colors: {
        paper: 'rgb(var(--paper) / <alpha-value>)',
        panel: {
          DEFAULT: 'rgb(var(--panel) / <alpha-value>)',
          2: 'rgb(var(--panel-2) / <alpha-value>)',
        },
        well: 'rgb(var(--well) / <alpha-value>)',
        sunken: 'rgb(var(--sunken) / <alpha-value>)',
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
          strong: 'rgb(var(--line-strong) / <alpha-value>)',
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
        sans: [
          'Inter',
          'Inter var',
          'system-ui',
          '-apple-system',
          'Segoe UI Variable Text',
          'Segoe UI',
          'PingFang SC',
          'HarmonyOS Sans SC',
          'Microsoft YaHei UI',
          'Noto Sans SC',
          'sans-serif',
        ],
        mono: [
          'JetBrains Mono',
          'Cascadia Code',
          'SFMono-Regular',
          'SF Mono',
          'ui-monospace',
          'Menlo',
          'Consolas',
          'monospace',
        ],
      },
      letterSpacing: { tightest: '-0.035em' },
      borderRadius: {
        // 圆润的节奏:外壳 24 / 分区 18 / 小块 16 / 控件 14
        panel: '24px',
        card: '18px',
        tile: '16px',
        control: '14px',
      },
      boxShadow: {
        panel: 'var(--shadow-1)',
        raised: 'var(--shadow-2)',
        float: 'var(--shadow-3)',
        pop: 'var(--shadow-pop)',
      },
      transitionDuration: { 150: '150ms', 220: '220ms', 380: '380ms' },
      keyframes: {
        rise: { '0%': { opacity: '0', transform: 'translateY(6px)' }, '100%': { opacity: '1', transform: 'translateY(0)' } },
        fade: { '0%': { opacity: '0' }, '100%': { opacity: '1' } },
        slide: { '0%': { opacity: '0', transform: 'translateX(24px)' }, '100%': { opacity: '1', transform: 'translateX(0)' } },
        'slide-in': { '0%': { opacity: '0', transform: 'translateX(-12px)' }, '100%': { opacity: '1', transform: 'translateX(0)' } },
        shimmer: {
          '0%': { backgroundPosition: '-180% 0' },
          '100%': { backgroundPosition: '180% 0' },
        },
      },
      animation: {
        rise: 'rise .32s cubic-bezier(.22,.68,0,1) both',
        fade: 'fade .2s ease both',
        slide: 'slide .28s cubic-bezier(.22,.68,0,1) both',
        'slide-in': 'slide-in .26s cubic-bezier(.22,.68,0,1) both',
        shimmer: 'shimmer 1.6s linear infinite',
      },
    },
  },
  plugins: [],
}