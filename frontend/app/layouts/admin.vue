<script setup lang="ts">
import { AppHeader } from '~/widgets/app-header'
</script>

<template>
  <div class="app-shell">
    <AppHeader />
    <nav
      class="admin-nav"
      aria-label="Админ-раздел"
    >
      <div class="admin-nav__inner">
        <NuxtLink to="/admin/lots">Лоты</NuxtLink>
        <NuxtLink to="/admin/rentals">Аренды</NuxtLink>
        <NuxtLink to="/admin/verification">Верификация</NuxtLink>
        <NuxtLink to="/admin/tickets">Тикеты</NuxtLink>
        <NuxtLink to="/admin/analytics">Аналитика</NuxtLink>
      </div>
    </nav>
    <main class="app-main">
      <slot />
    </main>
    <footer class="footer muted">
      Демо-стенд на мок-данных · Keep Rollin
    </footer>
  </div>
</template>

<style scoped>
.admin-nav {
  border-bottom: 1px solid var(--p-content-border-color);
  background: var(--p-content-background);
}

.admin-nav__inner {
  display: flex;
  gap: 4px;
  width: min(1180px, 100% - 32px);
  margin: 0 auto;
  padding: 8px 0;
  overflow-x: auto;
}

.admin-nav__inner a {
  padding: 6px 12px;
  border-radius: var(--p-content-border-radius);
  color: var(--p-text-color);
  text-decoration: none;
  white-space: nowrap;
}

.admin-nav__inner a.router-link-active {
  background: var(--p-highlight-background);
  color: var(--p-highlight-color);
}

.footer {
  padding: 16px;
  text-align: center;
  font-size: 0.85rem;
  border-top: 1px solid var(--p-content-border-color);
}

@media (max-width: 640px) {
  .admin-nav__inner {
    width: calc(100% - 24px);
  }
}
</style>
