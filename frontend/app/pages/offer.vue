<script setup lang="ts">
import { OfferMarkdown } from '~/entities/offer'
import { useCurrentOffer } from '~/features/offer-acceptance'
import { ErrorState, PageHeading } from '~/shared/ui'

useHead({ title: 'Оферта — Keep Rollin' })
const { data, error, pending, refresh } = await useCurrentOffer('public-current-offer')
</script>

<template>
  <div class="stack">
    <ErrorState
      v-if="error"
      :error="error"
      @retry="refresh"
    />
    <template v-else-if="data?.offer">
      <PageHeading
        :title="data.offer.title"
        :subtitle="`Версия ${data.offer.version}`"
      />
      <article class="panel">
        <OfferMarkdown :source="data.offer.body" />
      </article>
    </template>
    <p
      v-else-if="pending"
      role="status"
    >
      Загружаем оферту…
    </p>
    <p v-else>
      Оферта пока не опубликована.
    </p>
  </div>
</template>
