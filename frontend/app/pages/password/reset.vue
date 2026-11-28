<script setup lang="ts">
import { usePasswordReset } from '~/features/session/password'

useHead({
  title: 'Новый пароль — Keep Rollin',
  meta: [{ name: 'referrer', content: 'no-referrer' }],
})
if (import.meta.server) useResponseHeader('Referrer-Policy').value = 'no-referrer'

const { token, ready, password, confirmation, pending, completed, error, submit } = usePasswordReset()
</script>

<template>
  <Card class="password-card">
    <template #title>
      Новый пароль
    </template>
    <template #content>
      <div class="stack">
        <p
          v-if="!ready"
          role="status"
        >
          Загрузка формы…
        </p>
        <template v-else-if="completed">
          <Message
            severity="success"
            :closable="false"
          >
            Пароль изменён. Теперь можно войти с новым паролем.
          </Message>
          <NuxtLink to="/login">Перейти ко входу</NuxtLink>
        </template>
        <template v-else-if="!token">
          <Message
            severity="warn"
            :closable="false"
          >
            Ссылка недействительна, уже использована или устарела.
          </Message>
          <NuxtLink to="/password/forgot">Запросить новую ссылку</NuxtLink>
        </template>
        <form
          v-else
          class="stack"
          @submit.prevent="submit"
        >
          <div>
            <label for="new-password">Новый пароль</label>
            <Password
              v-model="password"
              input-id="new-password"
              :feedback="false"
              :input-props="{ autocomplete: 'new-password' }"
              required
              fluid
            />
          </div>
          <div>
            <label for="confirm-password">Повторите пароль</label>
            <Password
              v-model="confirmation"
              input-id="confirm-password"
              :feedback="false"
              :input-props="{ autocomplete: 'new-password' }"
              required
              fluid
            />
          </div>
          <Message
            v-if="error"
            severity="error"
            :closable="false"
          >
            {{ error }}
          </Message>
          <Button
            type="submit"
            label="Сохранить пароль"
            :loading="pending"
          />
        </form>
      </div>
    </template>
  </Card>
</template>

<style scoped>
.password-card {
  max-width: 420px;
  margin: 0 auto;
}
</style>
