<script setup lang="ts">
import { useSession } from '../../model/useSession'

const { logout } = useSession()

const onClick = async () => {
  logout()
  await navigateTo('/')
}
</script>

<template>
  <Button
    label="Выйти"
    icon="pi pi-sign-out"
    text
    size="small"
    @click="onClick"
  />
</template>
