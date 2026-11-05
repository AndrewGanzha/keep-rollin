<script setup lang="ts">
import type { NuxtError } from '#app'

const props = defineProps<{ error: NuxtError }>()

const goHome = () => clearError({ redirect: '/' })
</script>

<template>
  <div class="app-shell">
    <main
      class="app-main stack"
      style="align-items: center; justify-content: center; text-align: center"
    >
      <h1 class="section-title">
        {{ props.error.statusCode }}
      </h1>
      <p
        class="muted"
        style="margin: 0"
      >
        {{ props.error.statusMessage || 'Страница не найдена' }}
      </p>
      <Button
        label="На главную"
        @click="goHome"
      />
    </main>
  </div>
</template>
