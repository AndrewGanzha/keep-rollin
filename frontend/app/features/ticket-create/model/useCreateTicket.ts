import { createRentalTicket, uploadTicketPhoto, type CreateTicketRequest, type TicketReceipt } from '~/entities/ticket'
import { ApiError, useApi } from '~/shared/api'

const MAX_PHOTO_BYTES = 5 * 1024 * 1024
type TicketDraft = Pick<CreateTicketRequest, 'category' | 'description'>

interface TicketAttempt {
  rentalId: string
  files: readonly File[]
  payload: CreateTicketRequest
  key: string
}

export const useCreateTicket = () => {
  const api = useApi()
  const toast = useToast()

  const pending = ref(false)
  let attempt: TicketAttempt | undefined

  const prepareAttempt = async (
    rentalId: string,
    draft: TicketDraft,
    files: readonly File[],
  ): Promise<TicketAttempt> => {
    if (attempt?.rentalId === rentalId
      && attempt.payload.category === draft.category
      && attempt.payload.description === draft.description
      && attempt.files.length === files.length
      && attempt.files.every((file, index) => file === files[index])) {
      return attempt
    }

    const key = crypto.randomUUID()
    const uploads = await Promise.allSettled(files.map((file) => {
      if (file.size === 0 || file.size > MAX_PHOTO_BYTES) {
        return Promise.reject(new Error('Invalid photo size'))
      }
      return uploadTicketPhoto(api, file)
    }))
    const fileIds = uploads.flatMap(upload => upload.status === 'fulfilled' ? [upload.value] : [])
    return {
      rentalId,
      files,
      key,
      payload: { ...draft, file_ids: fileIds, photo_upload_failures: files.length - fileIds.length },
    }
  }

  const create = async (
    rentalId: string,
    draft: TicketDraft,
    files: readonly File[],
  ): Promise<TicketReceipt | null> => {
    if (pending.value) {
      return null
    }
    pending.value = true

    try {
      attempt = await prepareAttempt(rentalId, draft, files)
      const ticket = await createRentalTicket(api, rentalId, attempt.payload, attempt.key)
      const skippedPhotos = ticket.skipped_photo_count
      attempt = undefined
      toast.add({ severity: 'success', summary: `Обращение №${ticket.id.slice(-4)} принято`, life: 4000 })
      if (skippedPhotos > 0) {
        toast.add({ severity: 'warn', summary: `Не удалось прикрепить фото: ${skippedPhotos}`, life: 6000 })
      }
      return ticket
    } catch (caught) {
      const message = caught instanceof ApiError
        ? caught.message
        : 'Не удалось отправить обращение'
      toast.add({ severity: 'error', summary: message, life: 4000 })
      return null
    } finally {
      pending.value = false
    }
  }

  return { create, pending }
}
