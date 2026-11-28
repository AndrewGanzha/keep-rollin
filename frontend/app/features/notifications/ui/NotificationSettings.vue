<script setup lang="ts">
import { useApi } from '~/shared/api'
import { fetchNotificationPreferences, saveNotificationPreferences } from '../api/notifications'
import { createNotificationPreferences } from '../model/preferences'
import { useBrowserPush } from '../model/useBrowserPush'

const events: Record<string, string> = {
  'verification.approved': 'Верификация одобрена',
  'verification.rejected': 'Верификация отклонена',
  'booking.confirmed': 'Бронирование подтверждено',
  'rental.closed': 'Аренда завершена',
  'booking.cancelled': 'Бронирование отменено',
  'rental.ending_soon': 'Аренда скоро закончится',
  'rental.overdue.user': 'Ваша аренда просрочена',
  'rental.overdue.admin': 'Аренда клиента просрочена',
  'ticket.created.admin': 'Новое обращение клиента',
  'ticket.updated.user': 'Обращение обновлено',
  'ticket.resolved.user': 'Обращение решено',
}

const api = useApi()
const push = useBrowserPush()
const { account, token, status, busy, failedAction, operationError, refresh: refreshPush, enable, disable } = push
const { data, pending, saving, loadFailed, saveFailed, refresh, reset, setEmail, setPush } = createNotificationPreferences(
  () => fetchNotificationPreferences(api),
  patch => saveNotificationPreferences(api, patch),
)

const pushMessages = {
  checking: 'Проверяем подписку на push-уведомления…',
  off: 'В этом браузере нет активной подписки.',
  active: 'Подписка в этом браузере активна.',
  denied: 'Уведомления запрещены в настройках браузера. Разрешите их для этого сайта и вернитесь сюда.',
  install: 'На iPhone или iPad откройте меню «Поделиться», выберите «На экран Домой» и запустите сайт с домашнего экрана. Если появится переключатель «Открывать как веб-приложение», оставьте его включённым.',
  unsupported: 'Этот браузер или способ подключения не поддерживает push-уведомления.',
  unconfigured: 'Push-уведомления недоступны для этого проката.',
  'session-changed': 'Аккаунт в браузере изменился. Обновите страницу, чтобы проверить подписку.',
  error: 'Не удалось проверить подписку в этом браузере.',
}

const pushMessage = computed(() => {
  if (status.value !== 'error') return pushMessages[status.value]
  if (operationError.value) return operationError.value
  if (failedAction.value === 'enable') return 'Не удалось подключить push-уведомления в этом браузере.'
  if (failedAction.value === 'disable') return 'Не удалось завершить отключение push-уведомлений в этом браузере.'
  return pushMessages.error
})

const retryPush = () => {
  if (status.value === 'denied') return refreshPush()
  if (failedAction.value === 'enable') return enable()
  if (failedAction.value === 'disable') return disable()
  return refreshPush()
}

const refreshForAccount = () => {
  if (account.value && token.value) void refresh()
}
const onVisibility = () => {
  if (document.visibilityState === 'visible') refreshForAccount()
}

watch([account, token], () => {
  reset()
  refreshForAccount()
})
onMounted(() => {
  refreshForAccount()
  document.addEventListener('visibilitychange', onVisibility)
})
onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', onVisibility)
  reset()
})
</script>

<template>
  <section
    class="notification-section"
    aria-labelledby="browser-push-title"
  >
    <h2 id="browser-push-title">
      Push в этом браузере
    </h2>
    <p
      class="muted"
      role="status"
    >
      {{ pushMessage }}
    </p>
    <Button
      v-if="status === 'off'"
      label="Подключить браузер"
      :loading="busy"
      @click="enable"
    />
    <Button
      v-else-if="status === 'active'"
      label="Отключить браузер"
      severity="secondary"
      outlined
      :loading="busy"
      @click="disable"
    />
    <Button
      v-else-if="status === 'error' || status === 'denied'"
      :label="status === 'error' && failedAction !== 'refresh' ? 'Повторить' : 'Проверить снова'"
      severity="secondary"
      outlined
      :loading="busy"
      @click="retryPush"
    />
  </section>

  <section
    class="notification-section"
    aria-labelledby="account-notifications-title"
    :aria-busy="pending || saving"
  >
    <h2 id="account-notifications-title">
      Настройки аккаунта
    </h2>
    <p class="muted">
      Настройки действуют на всех ваших устройствах.
    </p>
    <Message
      v-if="loadFailed"
      severity="error"
    >
      <div class="row">
        <span>Не удалось загрузить настройки.</span>
        <Button
          label="Повторить"
          size="small"
          text
          @click="refresh"
        />
      </div>
    </Message>
    <Message
      v-if="saveFailed"
      severity="error"
    >
      Не удалось сохранить изменение. Предыдущее значение восстановлено.
    </Message>
    <template v-if="data">
      <div class="preference-row">
        <div>
          <label for="account-push">Push для обычных событий</label>
          <p
            id="account-push-help"
            class="muted"
          >
            Важные события могут приходить в подключённые браузеры при любом значении.
          </p>
        </div>
        <ToggleSwitch
          input-id="account-push"
          :model-value="data.push_enabled"
          :disabled="pending || saving"
          :pt="{ input: { 'aria-describedby': 'account-push-help' } }"
          @update:model-value="setPush"
        />
      </div>
      <h3>Уведомления по почте</h3>
      <ul class="event-list">
        <li
          v-for="(enabled, event, index) in data.email_by_event"
          :key="event"
          class="preference-row"
        >
          <div>
            <label :for="`event-email-${index}`">{{ events[event] ?? event }}</label>
            <p
              v-if="data.locked_events.includes(event)"
              :id="`event-email-lock-${index}`"
              class="muted"
            >
              Обязательное письмо о важном событии.
            </p>
          </div>
          <ToggleSwitch
            :input-id="`event-email-${index}`"
            :model-value="enabled"
            :disabled="pending || saving || data.locked_events.includes(event)"
            :pt="{ input: { 'aria-describedby': data.locked_events.includes(event) ? `event-email-lock-${index}` : undefined } }"
            @update:model-value="value => setEmail(event, value)"
          />
        </li>
      </ul>
    </template>
    <p
      v-else-if="!loadFailed"
      class="muted"
      role="status"
    >
      Загружаем настройки…
    </p>
  </section>
</template>

<style scoped>
.notification-section {
  display: grid;
  justify-items: start;
  gap: 12px;
  padding: 20px;
  border: 1px solid var(--p-content-border-color);
  border-radius: var(--p-content-border-radius);
  background: var(--p-content-background);
}

.notification-section h2,
.notification-section h3,
.notification-section p {
  margin: 0;
}

.notification-section h2 {
  font-size: 1.125rem;
}

.notification-section h3 {
  margin-top: 8px;
  font-size: 1rem;
}

.event-list {
  width: 100%;
  list-style: none;
  padding: 0;
  margin: 0;
}

.preference-row {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 0;
  border-top: 1px solid var(--p-content-border-color);
}

.preference-row p {
  margin-top: 4px;
  font-size: 0.875rem;
}

.preference-row :deep(.p-toggleswitch) {
  flex: 0 0 auto;
}
</style>
