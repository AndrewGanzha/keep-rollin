<script setup lang="ts">
defineProps<{ title: string; subtitle?: string }>()
</script>

<template>
  <header
    class="stack"
    style="gap: 4px"
  >
    <h1 class="section-title">
      {{ title }}
    </h1>
    <p
      v-if="subtitle"
      class="muted"
      style="margin: 0"
    >
      {{ subtitle }}
    </p>
  </header>
</template>
