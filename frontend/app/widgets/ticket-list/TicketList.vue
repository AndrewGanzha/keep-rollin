<script setup lang="ts">
import type { Ticket, TicketCategory } from '~/entities/ticket'
import { formatDateTime } from '~/shared/lib'
import { EmptyState } from '~/shared/ui'

withDefaults(defineProps<{ tickets: Ticket[]; loading?: boolean; timeZone?: string }>(), {
  loading: false,
  timeZone: undefined,
})

const categoryLabels: Record<TicketCategory, string> = {
  no_power: 'Не включается',
  no_drive: 'Не едет',
  battery: 'Аккумулятор',
  damage: 'Повреждение',
  other: 'Другое',
}
</script>

<template>
  <div
    v-if="loading"
    class="stack"
  >
    <Skeleton
      v-for="index in 2"
      :key="index"
      height="150px"
      border-radius="16px"
    />
  </div>

  <EmptyState
    v-else-if="tickets.length === 0"
    title="Обращений нет"
    description="Сообщить о неполадке можно из активной аренды в разделе «Мои аренды»"
  />

  <div
    v-else
    class="stack"
  >
    <Card
      v-for="ticket in tickets"
      :key="ticket.id"
    >
      <template #title>
        {{ ticket.lot.name }}
      </template>

      <template #subtitle>
        {{ categoryLabels[ticket.category] }} · {{ formatDateTime(ticket.created_at, timeZone) }}
      </template>

      <template #content>
        <div class="stack">
          <p style="margin: 0">
            {{ ticket.description }}
          </p>
          <span
            v-if="ticket.admin_comment"
            class="muted"
          >
            Ответ администратора: {{ ticket.admin_comment }}
          </span>
        </div>
      </template>
    </Card>
  </div>
</template>
