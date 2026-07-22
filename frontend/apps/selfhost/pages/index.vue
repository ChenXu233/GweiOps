<script setup lang="ts">
definePageMeta({ layout: false })
</script>

<template>
  <div class="min-h-screen bg-background">
    <!-- Nav -->
    <nav class="flex items-center justify-between px-6 py-4 border-b border-border">
      <span class="text-xl font-bold tracking-tight">既未 · Gwei</span>
      <div class="flex items-center gap-4">
        <NuxtLink to="/login" class="text-sm text-muted-foreground hover:text-foreground transition-colors">
          登录
        </NuxtLink>
        <NuxtLink
          to="/login"
          class="inline-flex items-center justify-center rounded-md font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 bg-primary text-primary-foreground hover:bg-primary/90 h-9 rounded-md px-3 text-xs"
        >
          免费开始
        </NuxtLink>
      </div>
    </nav>

    <!-- Hero -->
    <section class="text-center py-20 px-6">
      <h1 class="text-5xl font-bold tracking-tight mb-4">
        你的团队记忆，永不离职。
      </h1>
      <p class="text-lg text-muted-foreground max-w-lg mx-auto mb-8">
        GweiOps 是 DevOps 工具链的 AI 大脑。夜间自动值班，早晨从容审案。
      </p>
      <div class="flex items-center justify-center gap-3">
        <NuxtLink
          to="/login"
          class="inline-flex items-center justify-center rounded-md font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 bg-primary text-primary-foreground hover:bg-primary/90 h-11 rounded-md px-8 text-base"
        >
          免费开始
        </NuxtLink>
        <NuxtLink
          to="/dashboard"
          class="inline-flex items-center justify-center rounded-md font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 border border-input bg-background hover:bg-accent hover:text-accent-foreground h-11 rounded-md px-8 text-base"
        >
          查看演示
        </NuxtLink>
      </div>
    </section>

    <!-- Trust bar -->
    <section class="text-center py-6 text-sm text-muted-foreground">
      已为 <strong class="text-foreground">200+</strong> 团队自动修复
      <strong class="text-foreground">12,000+</strong> 个问题 · 平均 MTTR
      <strong class="text-foreground">8.2 分钟</strong>
    </section>

    <!-- Product screenshot -->
    <section class="max-w-4xl mx-auto px-6 pb-12">
      <div class="border border-border rounded-xl overflow-hidden">
        <div class="flex items-center gap-2 px-4 py-3 border-b border-border">
          <div class="h-2.5 w-2.5 rounded-full bg-border" />
          <div class="h-2.5 w-2.5 rounded-full bg-border" />
          <div class="h-2.5 w-2.5 rounded-full bg-border" />
          <div class="flex-1 text-center text-[11px] text-muted-foreground font-mono">
            app.gweiops.com/dashboard
          </div>
        </div>
        <div class="bg-background p-4">
          <div class="grid grid-cols-4 gap-px bg-border rounded-lg overflow-hidden">
            <div class="col-span-2 bg-card p-4">
              <div class="text-[9px] uppercase tracking-wider text-muted-foreground mb-2">整体态势</div>
              <div class="flex items-center gap-2 text-xs">
                <span class="h-1.5 w-1.5 rounded-full bg-green-500" />
                系统正常运行 · 连续 14 天无故障
              </div>
            </div>
            <div class="bg-card p-4">
              <div class="text-[9px] uppercase tracking-wider text-muted-foreground mb-2">待审</div>
              <div class="text-xl font-bold text-yellow-500">3</div>
            </div>
            <div class="bg-card p-4">
              <div class="text-[9px] uppercase tracking-wider text-muted-foreground mb-2">昨夜修复</div>
              <div class="text-xl font-bold text-green-500">7</div>
            </div>
            <div class="col-span-3 bg-card p-4">
              <div class="text-[9px] uppercase tracking-wider text-muted-foreground mb-2">待审案件</div>
              <div class="text-[11px] text-muted-foreground space-y-1">
                <div class="py-1 border-b border-border">#42 内存泄漏 — <span class="text-green-500">3 方案就绪</span></div>
                <div class="py-1 border-b border-border">CVE-2026-1234 — <span class="text-green-500">应急补丁完成</span></div>
                <div class="py-1">#89 文档缺失 — <span class="text-green-500">1 方案就绪</span></div>
              </div>
            </div>
            <div class="bg-card p-4">
              <div class="text-[9px] uppercase tracking-wider text-muted-foreground mb-2">MTTR</div>
              <div class="text-xl font-bold">8.2<span class="text-xs text-muted-foreground">min</span></div>
            </div>
            <div class="col-span-4 bg-card p-4">
              <div class="text-[9px] uppercase tracking-wider text-muted-foreground mb-2">昨夜回顾</div>
              <div class="text-[11px] text-muted-foreground flex gap-6">
                <span>03:17 内存泄漏 → ✅</span>
                <span>04:30 CVE 补丁 → ✅</span>
                <span>05:12 流量扩容 → ✅</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- Logos -->
    <section class="flex items-center justify-center gap-8 py-12 opacity-30">
      <span class="text-xl font-semibold tracking-wide">ByteDance</span>
      <span class="text-xl font-semibold tracking-wide">Alibaba</span>
      <span class="text-xl font-semibold tracking-wide">Tencent</span>
      <span class="text-xl font-semibold tracking-wide">Meituan</span>
      <span class="text-xl font-semibold tracking-wide">Xiaomi</span>
    </section>

    <!-- Footer -->
    <footer class="text-center py-8 text-xs text-muted-foreground border-t border-border">
      GweiOps — 摆渡未济，恒守既济。
    </footer>
  </div>
</template>
