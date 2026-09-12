export default defineNuxtConfig({
  extends: ['@gwei/core'],
  compatibilityDate: '2026-07-23',
  css: ['~/assets/css/main.css'],
  typescript: {
    strict: true
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
