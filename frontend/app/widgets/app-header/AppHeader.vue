<script setup lang="ts">
import { useSessionStore } from '~/entities/session'
import { useTenant } from '~/entities/tenant'
import { LogoutButton } from '~/features/session/logout'

const tenant = useTenant()
const session = useSessionStore()
const dark = useState('dark-mode', () => false)

useHead(() => ({
  htmlAttrs: { class: dark.value ? 'app-dark' : '' },
}))

const toggleTheme = () => {
  dark.value = !dark.value
}
</script>

<template>
  <header class="header">
    <div class="header__inner">
      <NuxtLink
        to="/"
        class="header__brand"
      >
        <i
          class="pi pi-bolt"
          aria-hidden="true"
        />
        <span>{{ tenant?.name ?? 'Keep Rollin' }}</span>
      </NuxtLink>

      <nav
        class="header__nav"
        aria-label="Основная навигация"
      >
        <NuxtLink
          to="/"
          class="header__link"
        >Каталог</NuxtLink>
        <NuxtLink
          v-if="session.isAuthenticated"
          to="/account/rentals"
          class="header__link"
        >
          Мои аренды
        </NuxtLink>
        <NuxtLink
          v-if="session.isStaff"
          to="/admin"
          class="header__link"
        >
          Админка
        </NuxtLink>
      </nav>

      <div
        class="row"
        style="gap: 8px"
      >
        <Button
          :icon="dark ? 'pi pi-sun' : 'pi pi-moon'"
          text
          rounded
          aria-label="Переключить тему"
          @click="toggleTheme"
        />

        <template v-if="session.isAuthenticated">
          <span class="muted header__user">{{ session.user?.name }}</span>
          <LogoutButton />
        </template>
        <NuxtLink
          v-else
          to="/login"
        >
          <Button
            label="Войти"
            size="small"
          />
        </NuxtLink>
      </div>
    </div>
  </header>
</template>

<style scoped>
.header {
  position: sticky;
  top: 0;
  z-index: 10;
  border-bottom: 1px solid var(--p-content-border-color);
  background: var(--p-content-background);
}

.header__inner {
  display: flex;
  align-items: center;
  gap: 16px;
  width: min(1180px, 100% - 32px);
  margin: 0 auto;
  padding: 12px 0;
}

.header__brand {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--p-primary-color);
  font-weight: 700;
  text-decoration: none;
  white-space: nowrap;
}

.header__nav {
  display: flex;
  gap: 4px;
  flex: 1;
}

.header__link {
  padding: 6px 10px;
  border-radius: var(--p-content-border-radius);
  color: var(--p-text-color);
  text-decoration: none;
}

.header__link.router-link-active {
  background: var(--p-highlight-background);
  color: var(--p-highlight-color);
}

.header__user {
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 640px) {
  .header__inner {
    width: calc(100% - 24px);
    gap: 8px;
    flex-wrap: wrap;
  }

  .header__nav {
    order: 3;
    width: 100%;
    flex: none;
    overflow-x: auto;
  }

  .header__user {
    display: none;
  }
}
</style>
