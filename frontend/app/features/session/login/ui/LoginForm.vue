<script setup lang="ts">
import { useLogin } from '../model/useLogin'

const email = ref('rider@example.com')
const password = ref('password123')

const { submit, pending, error } = useLogin()

const errorText = computed(() => {
  if (!error.value) {
    return ''
  }

  if (error.value.code === 'invalid_credentials') {
    return 'Неверный email или пароль'
  }

  return error.value.message
})

const onSubmit = () => submit(email.value.trim(), password.value)
</script>

<template>
  <Card class="login-card">
    <template #title>
      Вход
    </template>

    <template #content>
      <form
        class="stack"
        @submit.prevent="onSubmit"
      >
        <div class="field">
          <label for="email">Email</label>
          <InputText
            id="email"
            v-model="email"
            type="email"
            autocomplete="email"
            fluid
          />
        </div>

        <div class="field">
          <label for="password">Пароль</label>
          <Password
            v-model="password"
            input-id="password"
            :feedback="false"
            toggle-mask
            autocomplete="current-password"
            fluid
          />
        </div>

        <Message
          v-if="errorText"
          severity="error"
          size="small"
          :closable="false"
        >
          {{ errorText }}
        </Message>

        <Button
          type="submit"
          label="Войти"
          :loading="pending"
        />
        <p
          class="muted"
          style="margin: 0; font-size: 0.85rem"
        >
          Мок: любой email и пароль от 8 символов.
        </p>
      </form>
    </template>
  </Card>
</template>

<style scoped>
.login-card {
  max-width: 420px;
  margin: 0 auto;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field label {
  font-size: 0.9rem;
  font-weight: 600;
}
</style>
