<script setup lang="ts">
// 登录页仅 SaaS 档可见(selfhost 使用本地管理员令牌,尚无认证后端)
definePageMeta({ layout: false, modes: ['saas'] })
</script>

<template>
  <div class="relative flex min-h-screen items-center justify-center overflow-hidden bg-paper px-5">
    <div class="grid-bg pointer-events-none absolute inset-0" />

    <div class="relative w-full max-w-[380px]">
      <div class="mb-6 flex flex-col items-center gap-3">
        <span class="relative grid h-11 w-11 place-items-center rounded-[14px] bg-ink text-paper">
          <span class="font-mono text-[15px] font-semibold leading-none">未</span>
          <span class="absolute right-[4px] top-[4px] h-[6px] w-[6px] rounded-full bg-lime" />
        </span>
        <div class="text-center">
          <h1 class="text-[17px] font-semibold tracking-tightest">登录既未</h1>
          <p class="mt-1 text-[12.5px] text-ink-soft">夜里发生的事,早上只做判断。</p>
        </div>
      </div>

      <div class="glass rounded-panel border border-line/70 p-6 shadow-xl shadow-ink/5">
        <NuxtLink to="/dashboard" class="btn-solid h-10 w-full text-[13px]">
          <AppIcon name="github" :size="15" />
          使用 GitHub 登录
        </NuxtLink>

        <div class="my-4 flex items-center gap-3">
          <span class="h-px flex-1 bg-line" />
          <span class="mono-label">或者</span>
          <span class="h-px flex-1 bg-line" />
        </div>

        <NuxtLink to="/dashboard" class="btn-outline h-10 w-full text-[13px]">
          以管理员令牌进入
          <AppIcon name="arrow-right" :size="14" />
        </NuxtLink>
      </div>

      <p class="mt-5 text-center text-[11.5px] leading-relaxed text-ink-faint">
        登录即表示同意服务条款与隐私政策
      </p>
    </div>
  </div>
</template>
