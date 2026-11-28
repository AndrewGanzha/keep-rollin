<script setup lang="ts">
import QRCode from 'qrcode'

const props = defineProps<{
  secret: string
  otpauthUri: string
}>()

const image = ref('')

watch(() => props.otpauthUri, async (uri, _, onCleanup) => {
  let cancelled = false
  onCleanup(() => { cancelled = true })
  image.value = ''
  try {
    const source = await QRCode.toDataURL(uri, { width: 200 })
    if (!cancelled) {
      image.value = source
    }
  } catch {
    // The setup key is still available for manual entry.
  }
}, { immediate: true })
</script>

<template>
  <div class="stack">
    <p class="setup-instruction">
      Добавьте Keep Rollin в приложение для подтверждения входа.
      {{ image ? 'Отсканируйте QR-код или введите ключ вручную.' : 'Введите ключ вручную.' }}
    </p>
    <img
      v-if="image"
      :src="image"
      alt="QR-код настройки двухфакторной защиты"
      width="200"
      height="200"
    >
    <div class="setup-key">
      <strong>Ключ настройки</strong>
      <code>{{ secret }}</code>
    </div>
  </div>
</template>

<style scoped>
.setup-instruction {
  margin: 0;
}
.setup-key {
  display: grid;
  gap: 4px;
  overflow-wrap: anywhere;
}
</style>
