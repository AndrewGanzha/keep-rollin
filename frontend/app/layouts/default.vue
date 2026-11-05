<script setup lang="ts">
import { AppHeader } from '~/widgets/app-header'
</script>

<template>
  <div class="app-shell">
    <AppHeader />
    <main class="app-main">
      <slot />
    </main>
    <footer class="footer muted">
      Демо-стенд на мок-данных · Keep Rollin
    </footer>
  </div>
</template>

<style scoped>
.footer {
  padding: 16px;
  text-align: center;
  font-size: 0.85rem;
  border-top: 1px solid var(--p-content-border-color);
}
</style>
