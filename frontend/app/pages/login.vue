<script setup lang="ts">
import { LoginForm } from '~/features/session/login'

definePageMeta({ middleware: 'guest' })

useHead({ title: 'Вход — Keep Rollin' })
</script>

<template>
  <LoginForm />
</template>
