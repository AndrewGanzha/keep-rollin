<script setup lang="ts">
import { useLogin } from '../model/useLogin'
import MfaSetupDetails from './MfaSetupDetails.vue'

const email = ref('')
const password = ref('')
const code = ref('')
const title = ref<HTMLElement>()

const {
  stage, setup, recovery, pending, errorText, retryAfter,
  submit, requestSetup, submitCode, backToCredentials, downloadRecoveryCodes, continueAfterRecovery,
} = useLogin()

const heading = computed(() => ({
  credentials: 'Вход',
  setup: 'Настройка двухфакторной защиты',
  verify: 'Подтверждение входа',
  recovery: 'Коды восстановления',
})[stage.value])

watch(stage, () => {
  code.value = ''
  title.value?.focus()
}, { flush: 'post' })

const onSubmit = () => {
  if (pending.value || retryAfter.value) {
    return
  }
  const enteredPassword = password.value
  password.value = ''
  return submit(email.value.trim(), enteredPassword)
}

const onSubmitCode = () => {
  if (pending.value || retryAfter.value) {
    return
  }
  const enteredCode = code.value
  code.value = ''
  return submitCode(enteredCode)
}

const showDemoAccounts = import.meta.dev
const demoAccounts = [
  { label: 'Арендатор', email: 'rider@example.com' },
  { label: 'Админ', email: 'admin@example.com' },
  { label: 'Владелец', email: 'owner@example.com' },
]

const useDemo = (demoEmail: string) => {
  email.value = demoEmail
  password.value = 'password123'
}
</script>

<template>
  <Card class="login-card">
    <template #title>
      <h1
        ref="title"
        class="login-title"
        tabindex="-1"
      >
        {{ heading }}
      </h1>
    </template>

    <template #content>
      <div class="stack">
        <form
          v-if="stage === 'credentials'"
          class="stack"
          novalidate
          @submit.prevent="onSubmit"
        >
          <div class="field">
            <label for="email">Email</label>
            <InputText
              id="email"
              v-model="email"
              type="email"
              autocomplete="email"
              :disabled="pending"
              required
              fluid
            />
          </div>

          <div class="field">
            <label for="password">Пароль</label>
            <Password
              v-model="password"
              input-id="password"
              :feedback="false"
              :disabled="pending"
              :input-props="{ autocomplete: 'current-password' }"
              toggle-mask
              required
              fluid
            />
          </div>

          <Button
            type="submit"
            label="Войти"
            :disabled="retryAfter > 0"
            :loading="pending"
          />
          <NuxtLink to="/password/forgot">Забыли пароль?</NuxtLink>
          <NuxtLink to="/register">Зарегистрироваться</NuxtLink>

          <template v-if="showDemoAccounts">
            <p class="muted demo-label">
              Демо-аккаунты для разработки
            </p>
            <div class="row">
              <Button
                v-for="account in demoAccounts"
                :key="account.email"
                type="button"
                :label="account.label"
                :disabled="pending"
                size="small"
                text
                @click="useDemo(account.email)"
              />
            </div>
          </template>
        </form>

        <div
          v-else-if="stage === 'recovery' && recovery"
          class="stack"
        >
          <p class="instruction">
            Сохраните коды в надёжном месте. Каждый код можно использовать один раз,
            если приложение для подтверждения входа недоступно.
          </p>
          <ul class="recovery-codes">
            <li
              v-for="item in recovery.codes"
              :key="item"
            >
              <code>{{ item }}</code>
            </li>
          </ul>
          <Button
            type="button"
            :label="recovery.downloaded ? 'Коды скачаны' : 'Скачать коды'"
            :disabled="recovery.downloaded || !recovery.codes.length"
            icon="pi pi-download"
            @click="downloadRecoveryCodes"
          />
          <Button
            type="button"
            label="Продолжить"
            severity="secondary"
            :loading="pending"
            @click="continueAfterRecovery"
          />
        </div>

        <form
          v-else
          class="stack"
          @submit.prevent="onSubmitCode"
        >
          <MfaSetupDetails
            v-if="setup"
            :secret="setup.secret"
            :otpauth-uri="setup.otpauth_uri"
          />
          <div
            v-if="stage === 'verify' || setup"
            class="field"
          >
            <label for="mfa-code">Код подтверждения</label>
            <InputText
              id="mfa-code"
              v-model="code"
              autocomplete="one-time-code"
              aria-describedby="mfa-code-hint"
              :inputmode="stage === 'setup' ? 'numeric' : 'text'"
              :maxlength="stage === 'setup' ? 6 : 32"
              :disabled="pending"
              required
              fluid
            />
            <small
              id="mfa-code-hint"
              class="muted"
            >
              {{ stage === 'setup'
                ? 'Введите шесть цифр из приложения.'
                : 'Введите шесть цифр из приложения или код восстановления.' }}
            </small>
          </div>
          <Button
            v-if="stage === 'verify' || setup"
            type="submit"
            label="Подтвердить"
            :disabled="retryAfter > 0"
            :loading="pending"
          />
          <Button
            v-else
            type="button"
            label="Получить ключ настройки"
            :disabled="retryAfter > 0"
            :loading="pending"
            @click="requestSetup"
          />
          <Button
            type="button"
            label="Вернуться ко входу"
            severity="secondary"
            :disabled="pending"
            text
            @click="backToCredentials"
          />
        </form>

        <Message
          v-if="errorText"
          severity="error"
          size="small"
          :closable="false"
        >
          {{ errorText }}
        </Message>
        <p
          v-if="retryAfter"
          class="instruction"
        >
          Повторить через {{ retryAfter }} с
        </p>
      </div>
    </template>
  </Card>
</template>

<style scoped>
.login-card {
  max-width: 420px;
  margin: 0 auto;
}

.login-title {
  margin: 0;
  font: inherit;
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

.instruction,
.demo-label {
  margin: 0;
}

.demo-label {
  font-size: 0.85rem;
}

.recovery-codes {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin: 0;
  padding: 0;
  overflow-wrap: anywhere;
  list-style: none;
}
</style>
