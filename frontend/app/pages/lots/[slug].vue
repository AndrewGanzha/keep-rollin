<script setup lang="ts">
import { useSessionStore } from '~/entities/session'
import { BookingDialog } from '~/features/booking/create'
import { useLotPage } from '~/features/lot-page'
import { ErrorState } from '~/shared/ui'
import { LotDetails } from '~/widgets/lot-details'

const route = useRoute()
const slug = computed(() => String(route.params.slug))

const { lot, availability, lotError, labels, refresh } = await useLotPage(slug)
const bookingOpen = ref(false)
const session = useSessionStore()

const onBook = async () => {
  if (!session.isAuthenticated) {
    await navigateTo({ path: '/login', query: { next: route.fullPath } })
    return
  }

  bookingOpen.value = true
}

useHead(() => ({ title: lot.value ? `${lot.value.name} — Keep Rollin` : 'Лот — Keep Rollin' }))
</script>

<template>
  <div class="stack">
    <ErrorState
      v-if="lotError"
      :error="lotError"
      @retry="refresh"
    />

    <template v-else-if="lot">
      <LotDetails
        :lot="lot"
        :availability="availability"
        :labels="labels"
        @book="onBook"
      />
      <BookingDialog
        v-model:visible="bookingOpen"
        :lot="lot"
      />
    </template>
  </div>
</template>
