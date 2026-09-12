export default defineNuxtConfig({
  extends: ['@gwei/core'],
  compatibilityDate: '2026-07-23',
  css: ['~/assets/css/main.css'],
  typescript: {
    strict: true
  },
  runtimeConfig: {
    public: {
      useMock: process.env.NUXT_PUBLIC_USE_MOCK === 'true',
      // 部署档位：selfhost（默认，单租户）| saas（多租户完整形态）
      mode: process.env.NUXT_PUBLIC_DEPLOYMENT_MODE || 'selfhost'
    }
  }
})
