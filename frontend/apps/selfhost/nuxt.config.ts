export default defineNuxtConfig({
  extends: ['@gwei/core'],
  modules: ['@nuxtjs/tailwindcss'],
  compatibilityDate: '2026-07-23',

  // 自己的 main.css(设计令牌 + 组件层)替换模块默认注入的那份
  tailwindcss: { cssPath: '~/assets/css/main.css' },

  // 只装拉丁子集(约 24KB/字重),中文继续用系统字体。
  // 之前 Inter / JetBrains Mono 只在字体栈里挂着、机器上并没有,小字一直落在系统默认字体上。
  css: [
    '@fontsource/inter/latin-400.css',
    '@fontsource/inter/latin-500.css',
    '@fontsource/inter/latin-600.css',
    '@fontsource/jetbrains-mono/latin-400.css',
    '@fontsource/jetbrains-mono/latin-500.css',
  ],

  // 核心 layer 的组件不放前缀,直接 <AppIcon> / <PluginWidget>
  components: [
    { path: '~/components', pathPrefix: false },
    { path: '../../packages/core/components', pathPrefix: false },
  ],

  devtools: { enabled: false },

  // 核心层是工作区包,@gwei/core/* 的 exports 没有扩展名,
  // tsc 的 Bundler 解析认不出来,这里补一条路径映射给类型检查用(不影响运行时解析)。
  typescript: {
    strict: true,
    tsConfig: {
      compilerOptions: {
        paths: {
          '@gwei/core': ['../../../packages/core/nuxt.config.ts'],
          '@gwei/core/*': ['../../../packages/core/*'],
        },
      },
    },
  },

  app: {
    // 页面切换用 main.css 里的 .page-* 过渡,保持和卡片抬起同一条缓动
    pageTransition: { name: 'page', mode: 'out-in' },
    head: {
      htmlAttrs: { lang: 'zh-CN' },
      title: '既未 · Gwei Ops',
      meta: [
        { name: 'viewport', content: 'width=device-width, initial-scale=1, viewport-fit=cover' },
        { name: 'color-scheme', content: 'light dark' },
        { name: 'description', content: '把外部信号变成外部世界里已经验证过的改变。' },
      ],
      // 脚本完全没跑起来时,别让首屏那个启动画面一直挂着
      noscript: [
        {
          innerHTML: '<style>.boot{display:none!important}</style>',
        },
      ],
      script: [
        {
          // 首帧前定主题:避免亮暗模式闪一下
          innerHTML:
            "(function(){try{var m=localStorage.getItem('gwei-theme')||'system';var d=m==='dark'||(m==='system'&&window.matchMedia('(prefers-color-scheme: dark)').matches);var e=document.documentElement;if(d){e.classList.add('dark');}e.style.colorScheme=d?'dark':'light';}catch(e){}})()",
        },
      ],
    },
  },

  experimental: {
    // 控制台没有 route rules,不需要给客户端下发 app manifest;
    // 关掉可避开某些环境下 #app-manifest 虚拟模块解析失败。
    appManifest: false
  },

  runtimeConfig: {
    // engineUrl 仅服务端(代理)使用;浏览器一律走同源 /api
    engineUrl: process.env.NUXT_ENGINE_URL || 'http://localhost:8000',
    // 控制台令牌只在服务端使用:代理替浏览器带上,浏览器永远拿不到它
    engineToken: process.env.NUXT_ENGINE_TOKEN || '',
    public: {
      useMock: process.env.NUXT_PUBLIC_USE_MOCK === 'true',
      // 部署档位:selfhost(默认,单租户)| saas(多租户完整形态)
      mode: process.env.NUXT_PUBLIC_DEPLOYMENT_MODE || 'selfhost'
    }
  }
})