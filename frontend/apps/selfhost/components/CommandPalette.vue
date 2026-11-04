<script setup lang="ts">
interface PaletteItem {
  to: string
  label: string
  icon: string
  hint?: string
}

const props = defineProps<{ items: PaletteItem[] }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const q = ref('')
const inputEl = ref<HTMLInputElement | null>(null)
const active = ref(0)

const filtered = computed(() => {
  const needle = q.value.trim().toLowerCase()
  if (!needle) return props.items
  return props.items.filter(i => (i.label + ' ' + i.to).toLowerCase().includes(needle))
})

watch(filtered, () => {
  active.value = 0
})

onMounted(() => {
  nextTick(() => inputEl.value?.focus())
})

function go(item?: PaletteItem) {
  if (!item) return
  emit('close')
  navigateTo(item.to)
}

function onKey(e: KeyboardEvent) {
  const total = filtered.value.length
  if (e.key === 'Escape') {
    emit('close')
    return
  }
  if (e.key === 'ArrowDown' && total) {
    e.preventDefault()
    active.value = (active.value + 1) % total
  }
  if (e.key === 'ArrowUp' && total) {
    e.preventDefault()
    active.value = (active.value - 1 + total) % total
  }
  if (e.key === 'Enter') {
    e.preventDefault()
    go(filtered.value[active.value])
  }
}
</script>

<template>
  <Teleport to="body">
    <div class="fixed inset-0 z-50 flex items-start justify-center px-4 pt-[12vh]">
      <div class="absolute inset-0 animate-fade bg-ink/25 backdrop-blur-md" @click="emit('close')" />

      <div
        class="glass relative w-full max-w-[520px] animate-rise overflow-hidden rounded-2xl border border-line/70 shadow-2xl shadow-ink/10"
        role="dialog"
        aria-modal="true"
      >
        <div class="flex items-center gap-2.5 border-b border-line/70 px-4 py-3">
          <AppIcon name="search" :size="16" class="text-ink-faint" />
          <input
            ref="inputEl"
            v-model="q"
            type="text"
            placeholder="跳转到..."
            class="w-full bg-transparent text-[14px] text-ink outline-none placeholder:text-ink-faint"
            @keydown="onKey"
          >
          <button class="kbd" @click="emit('close')">Esc</button>
        </div>

        <ul class="max-h-[46vh] overflow-auto p-1.5">
          <li v-for="(item, i) in filtered" :key="item.to">
            <button
              class="flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-left transition-colors"
              :class="i === active ? 'bg-well text-ink' : 'text-ink-soft hover:bg-well/70'"
              @mouseenter="active = i"
              @click="go(item)"
            >
              <AppIcon :name="item.icon" :size="15" />
              <span class="flex-1 text-[13px] font-medium">{{ item.label }}</span>
              <span class="font-mono text-[11px] text-ink-faint">{{ item.to }}</span>
              <AppIcon v-if="i === active" name="arrow-right" :size="13" class="text-ink-faint" />
            </button>
          </li>
          <li v-if="!filtered.length" class="px-3 py-8 text-center text-[12px] text-ink-faint">
            没有匹配的页面
          </li>
        </ul>
      </div>
    </div>
  </Teleport>
</template>
