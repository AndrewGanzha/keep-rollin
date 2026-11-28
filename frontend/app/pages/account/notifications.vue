<script setup lang="ts">
import { NotificationSettings } from '~/features/notifications'
import { PageHeading } from '~/shared/ui'

definePageMeta({ middleware: ['auth'] })

useHead({ title: 'Уведомления' })
</script>

<template>
  <div class="stack notification-settings">
    <PageHeading title="Уведомления" />
    <NotificationSettings />
  </div>
</template>

<style scoped>
.notification-settings {
  max-width: 720px;
}
</style>
