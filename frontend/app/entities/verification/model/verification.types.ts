import type { components } from '~/shared/api/schema'

export type AdminVerificationRequestSummary = components['schemas']['AdminVerificationRequestSummary']
export type VerificationRequest = components['schemas']['VerificationRequest']
export type VerificationRequestPage = components['schemas']['VerificationRequestPage']
export type VerificationStatus = AdminVerificationRequestSummary['status']
export type VerificationDecisionRequest = components['schemas']['VerificationDecisionRequest']
