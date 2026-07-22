<script setup lang="ts">
import { cn } from '../utils/cn'
import Button from './ui/Button.vue'

defineProps<{
  icon: string
  title: string
  description: string
  action?: { label: string; href: string }
}>()
</script>

<template>
  <div :class="cn('flex flex-col items-center justify-center py-12 text-center', $attrs.class as string | undefined)">
    <div class="text-4xl mb-4">{{ $props.icon }}</div>
    <h3 class="text-lg font-semibold mb-2">{{ $props.title }}</h3>
    <p class="text-sm text-muted-foreground max-w-sm mb-6">{{ $props.description }}</p>
    <Button v-if="$props.action" as="a" :href="$props.action.href">
      {{ $props.action.label }}
    </Button>
  </div>
</template>
