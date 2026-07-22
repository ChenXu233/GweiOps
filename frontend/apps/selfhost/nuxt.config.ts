export default defineNuxtConfig({
  extends: ['@gwei/core'],
  compatibilityDate: '2026-07-23',
  css: ['~/assets/css/main.css'],
  typescript: {
    strict: true
  },
  runtimeConfig: {
    public: {
      useMock: process.env.NUXT_PUBLIC_USE_MOCK === 'true'
    }
  }
})
