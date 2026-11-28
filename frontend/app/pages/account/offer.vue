<script setup lang="ts">
import { OfferMarkdown } from '~/entities/offer'
import { useOfferAcceptance } from '~/features/offer-acceptance'
import { ErrorState, PageHeading } from '~/shared/ui'

definePageMeta({ middleware: 'auth' })
useHead({ title: 'Принятие оферты — Keep Rollin' })

const { current, offer, next, notice, accepting, accept } = useOfferAcceptance()
const { error, pending, refresh } = await current
</script>

<template>
  <div class="stack">
    <PageHeading title="Принятие оферты" />
    <ErrorState
      v-if="error"
      :error="error"
      @retry="refresh"
    />
    <p
      v-else-if="pending"
      role="status"
    >
      Загружаем актуальную оферту…
    </p>
    <template v-else-if="offer">
      <Message
        v-if="notice"
        severity="warn"
        :closable="false"
      >
        {{ notice }}
      </Message>
      <article class="panel">
        <h2>{{ offer.title }}</h2>
        <p class="muted">
          Версия {{ offer.version }}
        </p>
        <OfferMarkdown :source="offer.body" />
      </article>
      <div class="row">
        <Button
          label="Принять оферту"
          :loading="accepting"
          @click="accept"
        />
        <NuxtLink :to="next">Вернуться</NuxtLink>
      </div>
    </template>
    <template v-else>
      <Message
        severity="warn"
        :closable="false"
      >
        Оферта пока не опубликована.
      </Message>
      <NuxtLink :to="next">Вернуться</NuxtLink>
    </template>
  </div>
</template>
