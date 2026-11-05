<script setup lang="ts">
// 营销落地页仅 SaaS 档可见;selfhost 档由全局 middleware 重定向到 /dashboard
definePageMeta({ layout: false, modes: ['saas'] })

const pillars = [
  {
    icon: 'moon',
    tag: 'NIGHT SHIFT',
    title: '不等你醒来',
    body: '信号进来就在外部世界里执行,验证通过再报告。早上你看到的是结果,不是待办。',
  },
  {
    icon: 'shield-check',
    tag: 'REVERSIBLE',
    title: '一个人也敢打',
    body: '每个改变都带撤销路径和观察窗口。没人必须先审批,先做、可回滚远比慢更安全。',
  },
  {
    icon: 'plugins',
    tag: 'BINDINGS',
    title: '只绑定不自建',
    body: '监控、金丝雀、通知都是插件。引擎只负责编排与记账,不重复造已有的轮子。',
  },
]
</script>

<template>
  <div class="min-h-screen bg-paper text-ink">
    <header class="glass-bar sticky top-0 z-40 border-b border-line/60">
      <div class="mx-auto flex h-14 w-full max-w-[1080px] items-center justify-between px-5">
        <div class="flex items-center gap-2.5">
          <span class="relative grid h-7 w-7 place-items-center rounded-[9px] bg-ink text-paper">
            <span class="font-mono text-[11.5px] font-semibold leading-none">未</span>
            <span class="absolute right-[3px] top-[3px] h-[5px] w-[5px] rounded-full bg-lime" />
          </span>
          <span class="text-[15px] font-semibold tracking-tightest">既未</span>
          <span class="mono-label">GWEI OPS</span>
        </div>
        <div class="flex items-center gap-2">
          <NuxtLink to="/login" class="btn-ghost h-8 px-3 text-[12.5px]">登录</NuxtLink>
          <NuxtLink to="/login" class="btn-solid h-8 px-3.5 text-[12.5px]">免费开始</NuxtLink>
        </div>
      </div>
    </header>

    <section class="relative overflow-hidden">
      <div class="grid-bg pointer-events-none absolute inset-0" />
      <div class="relative mx-auto max-w-[1080px] px-5 pb-16 pt-20">
        <div class="inline-flex items-center gap-2 rounded-full border border-line bg-panel/70 px-3 py-1.5 backdrop-blur">
          <AppIcon name="zap" :size="12" class="text-brand" />
          <span class="font-mono text-[11.5px] tracking-wider text-ink-soft">人只在不可逆的地方拦一下</span>
        </div>

        <h1 class="mt-6 max-w-[760px] text-balance text-[44px] font-semibold leading-[1.08] tracking-tightest sm:text-[56px]">
          夜里发生的事,<br class="hidden sm:block">
          早上只做判断。
        </h1>

        <p class="mt-5 max-w-[520px] text-[14px] leading-relaxed text-ink-soft">
          信号 → 诊断修复 → 部署报告 → 学习或回滚。GweiOps 在外部世界里把改变做完并验证,
          人只处理真正不可回滚的那一类。
        </p>

        <div class="mt-7 flex flex-wrap items-center gap-2.5">
          <NuxtLink to="/login" class="btn-solid h-10 px-5 text-[13px]">
            免费开始
            <AppIcon name="arrow-right" :size="14" />
          </NuxtLink>
          <NuxtLink to="/dashboard" class="btn-outline h-10 px-5 text-[13px]">看演示控制台</NuxtLink>
        </div>

        <div class="mt-14 grid gap-px overflow-hidden rounded-panel bg-line sm:grid-cols-3">
          <div class="bg-lime p-6 text-lime-ink">
            <div class="font-mono text-[11px] uppercase tracking-[0.16em] text-lime-ink/55">MTTR</div>
            <div class="num mt-3 text-[40px] font-semibold leading-none tracking-tightest">8.2<span class="ml-1 text-[14px] font-normal opacity-60">分钟</span></div>
            <p class="mt-2 text-[12px] opacity-70">从信号到部署完成的中位耗时</p>
          </div>
          <div class="bg-panel p-6">
            <div class="mono-label">夜间修复</div>
            <div class="num mt-3 text-[40px] font-semibold leading-none tracking-tightest">12,000<span class="ml-1 text-[14px] font-normal text-ink-faint">+</span></div>
            <p class="mt-2 text-[12px] text-ink-soft">在没人看着的时候完成并验证</p>
          </div>
          <div class="bg-solid p-6 text-solid-ink">
            <div class="font-mono text-[11px] uppercase tracking-[0.16em] text-solid-ink/45">回滚</div>
            <div class="num mt-3 text-[40px] font-semibold leading-none tracking-tightest">0.6<span class="ml-1 text-[14px] font-normal opacity-50">%</span></div>
            <p class="mt-2 text-[12px] opacity-55">只有千分之六需要回退</p>
          </div>
        </div>
      </div>
    </section>

    <section class="mx-auto max-w-[1080px] px-5 pb-24">
      <div class="grid gap-4 sm:grid-cols-3">
        <article
          v-for="p in pillars"
          :key="p.tag"
          class="rounded-panel border border-line bg-panel p-6 transition-colors hover:border-ink/20"
        >
          <div class="flex items-center justify-between">
            <span class="grid h-9 w-9 place-items-center rounded-xl bg-well text-ink-soft">
              <AppIcon :name="p.icon" :size="16" />
            </span>
            <span class="mono-label">{{ p.tag }}</span>
          </div>
          <h2 class="mt-5 text-[15px] font-semibold tracking-tight">{{ p.title }}</h2>
          <p class="mt-2 text-[12.5px] leading-relaxed text-ink-soft">{{ p.body }}</p>
        </article>
      </div>
    </section>

    <footer class="border-t border-line/60">
      <div class="mx-auto flex max-w-[1080px] flex-wrap items-center justify-between gap-2 px-5 py-8">
        <span class="mono-label">既未 · GWEI OPS</span>
        <span class="text-[12px] text-ink-faint">摆渡未济,恒守既济。</span>
      </div>
    </footer>
  </div>
</template>