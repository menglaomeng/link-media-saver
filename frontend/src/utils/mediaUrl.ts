import type { MediaItem } from '@/types/media'

export const apiBase = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')

export function absoluteMediaUrl(path: string) {
  if (/^https?:\/\//i.test(path)) return path
  return `${apiBase}${path}`
}

export function attachmentUrl(item: MediaItem) {
  if (!item.download_url.startsWith('/media/')) {
    const params = new URLSearchParams({
      url: item.download_url,
      filename: item.filename
    })
    return `${apiBase}/api/download-remote?${params.toString()}`
  }

  const mediaPath = item.download_url
    .replace(/^\/media\//, '')
    .split('/')
    .map(encodeURIComponent)
    .join('/')

  return `${apiBase}/api/download/${mediaPath}`
}
