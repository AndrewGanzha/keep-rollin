export const safeNext = (next: unknown, fallback: string): string => {
  if (typeof next !== 'string' || !next.startsWith('/') || next.startsWith('//') || next.includes('\\')) {
    return fallback
  }
  if ([...next].some(character => {
    const code = character.charCodeAt(0)
    return code <= 32 || code === 127
  })) return fallback

  const origin = 'https://keep-rollin.invalid'
  try {
    const target = new URL(next, origin)
    return target.origin === origin && !target.pathname.startsWith('//') ? next : fallback
  } catch {
    return fallback
  }
}
