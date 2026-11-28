<script setup lang="ts">
import { useSessionStore } from '~/entities/session'
import { PageHeading } from '~/shared/ui'

definePageMeta({ middleware: 'auth' })

const session = useSessionStore()

const statusCopy = {
  pending: { label: 'Ожидает проверки', severity: 'warn' },
  approved: { label: 'Подтверждена', severity: 'success' },
  rejected: { label: 'Отклонена', severity: 'danger' },
} as const
const status = computed(() => session.user ? statusCopy[session.user.verification_status] : null)
</script>

<template>
  <div class="stack">
    <PageHeading title="Верификация" />
    <section
      v-if="status"
      class="panel"
      aria-label="Статус верификации"
    >
      <Tag
        :value="status.label"
        :severity="status.severity"
      />
    </section>
  </div>
</template>
