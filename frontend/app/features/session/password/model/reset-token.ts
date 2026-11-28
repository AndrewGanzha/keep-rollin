export const readPasswordResetToken = (query: unknown, hash: string): string | null => {
  const fragmentTokens = new URLSearchParams(hash.replace(/^#/, '')).getAll('token')
  if (fragmentTokens.length > 1) return null
  const value = fragmentTokens[0] ?? query
  return typeof value === 'string' && /^[a-zA-Z0-9_-]{20,512}$/.test(value) ? value : null
}
