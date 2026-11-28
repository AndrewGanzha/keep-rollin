<script setup lang="ts">
import { OfferMarkdown, type OfferVersion } from '~/entities/offer'
import { useSessionStore } from '~/entities/session'
import { useTenant } from '~/entities/tenant'
import { useAdminOffers } from '~/features/admin-offers'
import { EmptyState, ErrorState, PageHeading } from '~/shared/ui'

definePageMeta({
  layout: 'admin',
  middleware: ['auth', 'role', () => {
    if (!useSessionStore().can('offers.manage')) {
      return navigateTo('/admin', { replace: true })
    }
  }],
})

useHead({ title: 'Оферты — админка' })

const tenant = useTenant()
const dateTime = computed(() => new Intl.DateTimeFormat('ru-RU', {
  dateStyle: 'short',
  timeStyle: 'short',
  timeZone: tenant.value?.timezone,
}))

const statusTags: Record<OfferVersion['status'], { label: string; severity: 'warn' | 'success' | 'secondary' }> = {
  draft: { label: 'Черновик', severity: 'warn' },
  active: { label: 'Действует', severity: 'success' },
  archived: { label: 'В архиве', severity: 'secondary' },
}

const {
  request, history, historyError, historyPending, refresh, page, pageCount, changePage,
  editor, editable, titleIssue, bodyIssue, canSave, openEditor, closeEditor, save,
  confirmation, preparePublish, closeConfirmation, confirmPublish, action, busy, actionError, notice,
} = useAdminOffers()
await request
</script>

<template>
  <div class="stack">
    <div class="row heading">
      <PageHeading title="Оферты" />
      <Button
        label="Создать черновик"
        icon="pi pi-plus"
        :disabled="busy"
        @click="openEditor()"
      />
    </div>

    <Message
      v-if="actionError && !editor && !confirmation"
      severity="error"
    >
      {{ actionError }}
    </Message>
    <Message
      v-if="notice"
      severity="success"
    >
      {{ notice }}
    </Message>
    <p
      v-if="action === 'prepare'"
      class="muted"
      role="status"
    >
      Проверяем действующую версию…
    </p>

    <ErrorState
      v-if="historyError"
      :error="historyError"
      @retry="refresh()"
    />
    <template v-else>
      <DataTable
        :value="history?.items ?? []"
        :loading="historyPending"
        data-key="id"
        size="small"
        striped-rows
        scrollable
        aria-label="История версий оферты"
      >
        <template #empty>
          <EmptyState
            v-if="!historyPending"
            title="Оферт пока нет"
            description="Создайте черновик первой версии"
          />
        </template>
        <Column
          field="version"
          header="Версия"
        />
        <Column header="Название">
          <template #body="{ data }">
            <span class="offer-title">{{ data.title }}</span>
          </template>
        </Column>
        <Column header="Статус">
          <template #body="{ data }">
            <Tag
              :severity="statusTags[(data as OfferVersion).status].severity"
              :value="statusTags[(data as OfferVersion).status].label"
            />
          </template>
        </Column>
        <Column header="Создана">
          <template #body="{ data }">
            <time :datetime="data.created_at">{{ dateTime.format(new Date(data.created_at)) }}</time>
          </template>
        </Column>
        <Column header="Опубликована">
          <template #body="{ data }">
            <time
              v-if="data.published_at"
              :datetime="data.published_at"
            >{{ dateTime.format(new Date(data.published_at)) }}</time>
            <span v-else>—</span>
          </template>
        </Column>
        <Column header="Действия">
          <template #body="{ data }">
            <div class="row actions">
              <Button
                :label="data.status === 'draft' ? 'Редактировать' : 'Открыть'"
                :aria-label="`${data.status === 'draft' ? 'Редактировать' : 'Открыть'} версию №${data.version}`"
                size="small"
                text
                :disabled="busy || historyPending"
                @click="openEditor(data)"
              />
              <Button
                v-if="data.status === 'draft'"
                label="Опубликовать"
                :aria-label="`Опубликовать версию №${data.version}`"
                size="small"
                outlined
                :disabled="busy || historyPending"
                @click="preparePublish(data)"
              />
            </div>
          </template>
        </Column>
      </DataTable>

      <nav
        v-if="pageCount > 1"
        class="row pagination"
        aria-label="Страницы истории оферт"
      >
        <Button
          label="Назад"
          aria-label="Предыдущая страница"
          icon="pi pi-chevron-left"
          size="small"
          text
          :disabled="page === 1 || busy || historyPending"
          @click="changePage(page - 1)"
        />
        <span role="status">Страница {{ page }} из {{ pageCount }}</span>
        <Button
          label="Вперёд"
          aria-label="Следующая страница"
          icon="pi pi-chevron-right"
          icon-pos="right"
          size="small"
          text
          :disabled="page === pageCount || busy || historyPending"
          @click="changePage(page + 1)"
        />
      </nav>
    </template>

    <Dialog
      :visible="editor !== null"
      :header="editor?.offer ? `Оферта версии №${editor.offer.version}` : 'Новый черновик оферты'"
      :style="{ width: '760px', maxWidth: 'calc(100vw - 24px)' }"
      :closable="!busy"
      :close-on-escape="!busy"
      modal
      @update:visible="!$event && closeEditor()"
    >
      <form
        v-if="editor && editable"
        class="stack"
        @submit.prevent="save"
      >
        <div class="field">
          <label for="offer-title">Название</label>
          <InputText
            id="offer-title"
            v-model="editor.title"
            :disabled="busy"
            :readonly="editor.stale"
            :invalid="Boolean(editor.title && titleIssue)"
            :aria-describedby="editor.title && titleIssue ? 'offer-title-error' : undefined"
            required
            fluid
          />
          <small
            v-if="editor.title && titleIssue"
            id="offer-title-error"
            class="field-error"
          >{{ titleIssue }}</small>
        </div>
        <div class="field">
          <label for="offer-body">Текст оферты в Markdown</label>
          <Textarea
            id="offer-body"
            v-model="editor.body"
            :disabled="busy"
            :readonly="editor.stale"
            :invalid="Boolean(editor.body && bodyIssue)"
            :aria-describedby="editor.body && bodyIssue ? 'offer-body-error' : undefined"
            rows="9"
            required
            fluid
          />
          <small
            v-if="editor.body && bodyIssue"
            id="offer-body-error"
            class="field-error"
          >{{ bodyIssue }}</small>
        </div>
        <section
          v-if="editor.body.trim()"
          class="offer-preview"
          aria-labelledby="offer-preview-title"
        >
          <h2 id="offer-preview-title">
            Предпросмотр
          </h2>
          <h3 v-if="editor.title.trim()">
            {{ editor.title.trim() }}
          </h3>
          <OfferMarkdown :source="editor.body.trim()" />
        </section>

        <Message
          v-if="actionError"
          severity="error"
        >
          {{ actionError }}
        </Message>
        <div class="row dialog-actions">
          <Button
            :label="editor.stale ? 'Закрыть' : 'Отмена'"
            type="button"
            text
            :disabled="busy"
            @click="closeEditor"
          />
          <Button
            v-if="!editor.stale"
            label="Сохранить черновик"
            type="submit"
            :disabled="!canSave"
            :loading="action === 'save'"
          />
        </div>
      </form>
      <article
        v-else-if="editor?.offer"
        class="stack offer-preview"
      >
        <div class="row">
          <Tag
            :severity="statusTags[editor.offer.status].severity"
            :value="statusTags[editor.offer.status].label"
          />
          <span
            v-if="editor.offer.published_at"
            class="muted"
          >
            Опубликована <time :datetime="editor.offer.published_at">{{ dateTime.format(new Date(editor.offer.published_at)) }}</time>
          </span>
        </div>
        <h2>{{ editor.title }}</h2>
        <OfferMarkdown :source="editor.body" />
      </article>
    </Dialog>

    <Dialog
      :visible="confirmation !== null"
      header="Подтверждение публикации"
      :style="{ width: '520px', maxWidth: 'calc(100vw - 24px)' }"
      :closable="!busy"
      :close-on-escape="!busy"
      modal
      @update:visible="!$event && closeConfirmation()"
    >
      <div
        v-if="confirmation"
        class="stack publish-summary"
      >
        <p>
          Оферта версии <strong>№{{ confirmation.draft.version }} «{{ confirmation.draft.title }}»</strong> станет действующей.
        </p>
        <p v-if="confirmation.current">
          Действующая версия <strong>№{{ confirmation.current.version }} «{{ confirmation.current.title }}»</strong> уйдёт в архив.
        </p>
        <p>Перед бронированием арендаторы должны будут принять опубликованную версию.</p>
        <Message
          v-if="actionError"
          severity="error"
        >
          {{ actionError }}
        </Message>
      </div>
      <template #footer>
        <Button
          label="Отмена"
          text
          :disabled="busy"
          @click="closeConfirmation"
        />
        <Button
          label="Подтвердить публикацию"
          :loading="action === 'publish'"
          :disabled="busy"
          @click="confirmPublish"
        />
      </template>
    </Dialog>
  </div>
</template>

<style scoped>
.heading {
  justify-content: space-between;
}

.offer-title,
.offer-preview,
.publish-summary {
  overflow-wrap: anywhere;
}

.actions {
  gap: 4px;
}

.pagination {
  justify-content: center;
}

.field {
  display: grid;
  gap: 6px;
}

.field-error {
  color: var(--p-form-field-invalid-placeholder-color);
}

.dialog-actions {
  justify-content: flex-end;
}

.offer-preview h2,
.offer-preview h3,
.publish-summary p {
  margin: 0;
}

section.offer-preview {
  display: grid;
  gap: 8px;
  padding: 16px;
  border: 1px solid var(--p-content-border-color);
  border-radius: var(--p-content-border-radius);
}
</style>
