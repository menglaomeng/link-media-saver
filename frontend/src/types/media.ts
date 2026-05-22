export type MediaKind = 'image' | 'video' | 'audio' | 'file'

export interface MediaItem {
  filename: string
  kind: MediaKind
  size: number
  mime_type: string
  download_url: string
}

export interface ExtractResponse {
  success: boolean
  source_url: string
  resolved_url: string
  title: string
  extractor: string
  items: MediaItem[]
  warnings: string[]
}
