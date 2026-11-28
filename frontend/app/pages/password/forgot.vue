<script setup lang="ts">
import { usePasswordForgot } from '~/features/session/password'

useHead({ title: 'Восстановление пароля — Keep Rollin' })

const { email, pending, sent, failed, submit } = usePasswordForgot()
</script>

<template>
  <Card class="password-card">
    <template #title>
      Восстановление пароля
    </template>
    <template #content>
      <div class="stack">
        <Message
          v-if="sent"
          severity="success"
          :closable="false"
        >
          Если аккаунт существует, на указанный email придёт письмо со ссылкой для смены пароля.
        </Message>
        <form
          v-else
          class="stack"
          @submit.prevent="submit"
        >
          <div>
            <label for="reset-email">Email</label>
            <InputText
              id="reset-email"
              v-model="email"
              type="email"
              autocomplete="email"
              maxlength="254"
              required
              fluid
            />
          </div>
          <Message
            v-if="failed"
            severity="error"
            :closable="false"
          >
            Не удалось отправить запрос. Проверьте адрес и попробуйте ещё раз.
          </Message>
          <Button
            type="submit"
            label="Отправить ссылку"
            :loading="pending"
          />
        </form>
        <NuxtLink to="/login">Вернуться ко входу</NuxtLink>
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
