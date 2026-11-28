<script setup lang="ts">
import { OfferMarkdown } from '~/entities/offer'
import { useRegistration } from '~/features/session/register'
import { ErrorState, PageHeading } from '~/shared/ui'

definePageMeta({ middleware: 'guest' })
useHead({ title: 'Регистрация — Keep Rollin' })

const { values, fields, current, offer, consent, message, pending, created, login, submit } = useRegistration()
const terms = ref<HTMLDetailsElement>()
const { error, pending: loadingOffer, refresh } = await current
</script>

<template>
  <div class="registration stack">
    <PageHeading title="Регистрация" />
    <Card>
      <template #content>
        <div
          v-if="created"
          class="stack"
        >
          <Message
            v-if="message"
            severity="warn"
            :closable="false"
          >
            {{ message }}
          </Message>
          <NuxtLink
            v-if="!pending"
            :to="login"
          >Войти и продолжить</NuxtLink>
        </div>
        <form
          v-else
          class="stack"
          novalidate
          @submit.prevent="submit"
        >
          <div class="field">
            <label for="register-name">Имя</label>
            <InputText
              id="register-name"
              v-model="values.name"
              autocomplete="name"
              :invalid="!!fields.name"
              :disabled="pending"
              fluid
            />
            <small
              v-if="fields.name"
              class="field-error"
            >{{ fields.name }}</small>
          </div>
          <div class="field">
            <label for="register-email">Email</label>
            <InputText
              id="register-email"
              v-model="values.email"
              type="email"
              autocomplete="email"
              :invalid="!!fields.email"
              :disabled="pending"
              required
              fluid
            />
            <small
              v-if="fields.email"
              class="field-error"
              role="alert"
            >{{ fields.email }}</small>
          </div>
          <div class="field">
            <label for="register-phone">Телефон</label>
            <InputText
              id="register-phone"
              v-model="values.phone"
              type="tel"
              autocomplete="tel"
              :invalid="!!fields.phone"
              :disabled="pending"
              fluid
            />
            <small
              v-if="fields.phone"
              class="field-error"
            >{{ fields.phone }}</small>
          </div>
          <div class="field">
            <label for="register-password">Пароль</label>
            <Password
              v-model="values.password"
              input-id="register-password"
              :feedback="false"
              :input-props="{ autocomplete: 'new-password' }"
              :invalid="!!fields.password"
              :disabled="pending"
              toggle-mask
              required
              fluid
            />
            <small
              v-if="fields.password"
              class="field-error"
              role="alert"
            >{{ fields.password }}</small>
          </div>
          <ErrorState
            v-if="error"
            :error="error"
            @retry="refresh"
          />
          <p
            v-else-if="loadingOffer"
            role="status"
          >
            Загружаем текст оферты…
          </p>
          <template v-else-if="offer">
            <details
              id="register-offer-terms"
              ref="terms"
            >
              <summary>{{ offer.title }} · версия {{ offer.version }}</summary>
              <OfferMarkdown :source="offer.body" />
            </details>
            <div class="row">
              <Checkbox
                v-model="consent"
                input-id="register-consent"
                binary
                :disabled="pending"
              />
              <label for="register-consent">Принимаю оферту версии {{ offer.version }}</label>
              <a
                href="#register-offer-terms"
                @click="terms?.setAttribute('open', '')"
              >Читать текст оферты</a>
            </div>
          </template>
          <Message
            v-if="message"
            severity="error"
            :closable="false"
          >
            {{ message }}
          </Message>
          <Button
            type="submit"
            label="Создать аккаунт"
            :loading="pending"
            :disabled="loadingOffer || !!error"
          />
          <NuxtLink to="/login">Уже есть аккаунт? Войти</NuxtLink>
        </form>
      </template>
    </Card>
  </div>
</template>

<style scoped>
.registration {
  max-width: 600px;
  margin: 0 auto;
}

.field {
  display: grid;
  gap: 6px;
}

.field-error {
  color: var(--p-red-600);
}

summary {
  cursor: pointer;
}
</style>
