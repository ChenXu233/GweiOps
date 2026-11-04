export default defineNuxtConfig({
  extends: ['@gwei/core'],
  modules: ['@nuxtjs/tailwindcss'],
  compatibilityDate: '2026-07-23',
  css: ['~/assets/css/main.css'],
  typescript: {
    strict: true
  },
  experimental: {
    // 控制台没有 route rules,不需要给客户端下发 app manifest;
    // 关掉可避开某些环境下 #app-manifest 虚拟模块解析失败。
    appManifest: false
  },
  runtimeConfig: {
    // engineUrl 仅服务端(代理)使用;浏览器一律走同源 /api
    engineUrl: process.env.NUXT_ENGINE_URL || 'http://localhost:8000',
    public: {
      useMock: process.env.NUXT_PUBLIC_USE_MOCK === 'true',
      // 部署档位：selfhost（默认，单租户）| saas（多租户完整形态）
      mode: process.env.NUXT_PUBLIC_DEPLOYMENT_MODE || 'selfhost'
    }
  }
})
