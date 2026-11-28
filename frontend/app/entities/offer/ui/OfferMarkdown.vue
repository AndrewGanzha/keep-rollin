<script setup lang="ts">
import { renderOfferMarkdown } from '../model/markdown'

const props = defineProps<{ source: string }>()
const rendered = computed(() => renderOfferMarkdown(props.source))
</script>

<template>
  <!-- markdown-it escapes HTML and validates link protocols. -->
  <!-- eslint-disable vue/no-v-html -->
  <div
    class="offer-markdown"
    v-html="rendered"
  />
  <!-- eslint-enable vue/no-v-html -->
</template>

<style scoped>
.offer-markdown {
  overflow-wrap: anywhere;
  line-height: 1.6;
}

.offer-markdown :deep(pre) {
  padding: 12px;
  overflow-x: auto;
  background: var(--p-content-hover-background);
}

.offer-markdown :deep(table) {
  display: block;
  overflow-x: auto;
  border-collapse: collapse;
}

.offer-markdown :deep(td), .offer-markdown :deep(th) {
  padding: 6px 10px;
  border: 1px solid var(--p-content-border-color);
}
</style>
