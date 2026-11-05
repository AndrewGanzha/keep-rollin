import type { components } from '~/shared/api/schema'

export type VerificationRequest = components['schemas']['VerificationRequest']
export type VerificationRequestPage = components['schemas']['VerificationRequestPage']
export type VerificationStatus = VerificationRequest['status']
export type VerificationDecisionRequest = components['schemas']['VerificationDecisionRequest']
