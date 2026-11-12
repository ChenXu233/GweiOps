<script setup lang="ts">
// 首屏:服务端直出这一屏,水合完成后淡出。
// 它只负责"页面还没画出来"的这段时间,不做假进度——没有真实阶段就不编阶段。
const booting = ref(true)
const slow = ref(false)

let slowTimer: ReturnType<typeof setTimeout> | null = null

onMounted(() => {
  slowTimer = setTimeout(() => {
    slow.value = true
  }, 5000)

  const dismiss = () => {
    booting.value = false
    if (slowTimer) clearTimeout(slowTimer)
  }

  // 让浏览器先把首帧画出来,再移除,避免白屏闪一下
  requestAnimationFrame(() => {
    setTimeout(dismiss, 160)
  })

  // rAF 在后台标签页、无头浏览器里可能一直不触发;那会把启动画面永久留在屏幕上。
  // 兜底计时器和它赛跑,谁先到都算数。
  setTimeout(dismiss, 600)
})

onUnmounted(() => {
  if (slowTimer) clearTimeout(slowTimer)
})
</script>

<template>
  <div>
    <NuxtLoadingIndicator :height="2" color="#c6f24e" :duration="1800" :throttle="120" />

    <NuxtLayout>
      <NuxtPage />
    </NuxtLayout>

    <Transition name="boot">
      <div v-if="booting" class="boot app-bg" aria-live="polite" aria-label="正在载入控制台">
        <div class="boot-mark">
          <span>未</span>
          <span class="boot-dot" aria-hidden="true" />
        </div>

        <div class="text-center">
          <p class="text-[15px] font-semibold leading-none tracking-tightest">既未</p>
          <p class="mono-label mt-2">GWEI OPS</p>
        </div>

        <p class="font-mono text-[12px] leading-none tracking-[0.02em] text-ink-faint">
          &gt; {{ slow ? '还在载入,网络或引擎可能有点慢' : '正在载入控制台' }}<span
            class="boot-caret"
            aria-hidden="true"
          />
        </p>
      </div>
    </Transition>
  </div>
</template>
