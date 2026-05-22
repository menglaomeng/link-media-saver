import { computed, ref } from 'vue'
import type { ExtractResponse, MediaItem } from '@/types/media'
import { apiBase, attachmentUrl } from '@/utils/mediaUrl'

type DownloadPhase = 'idle' | 'resolving' | 'downloading' | 'done'

const NATIVE_DOWNLOAD_DELAY = 600

export function useMediaExtractor() {
  const linkText = ref('')
  const loading = ref(false)
  const downloadingUrl = ref('')
  const error = ref('')
  const result = ref<ExtractResponse | null>(null)
  const phase = ref<DownloadPhase>('idle')
  const currentIndex = ref(0)
  const totalCount = ref(0)
  const currentFilename = ref('')
  const loadedBytes = ref(0)
  const totalBytes = ref(0)
  const nativeDownloadCount = ref(0)
  const currentUsesNativeDownload = ref(false)

  const canSubmit = computed(() => linkText.value.trim().length > 0 && !loading.value)
  const hasResult = computed(() => phase.value !== 'idle')
  const visibleItems = computed(() => result.value?.items ?? [])
  const resultText = computed(() => {
    const title = result.value?.title?.trim() ?? ''
    return title.replace(/\s+-\s+(抖音|小红书|Douyin|XiaoHongShu)$/i, '').trim()
  })
  const progressPercent = computed(() => {
    if (phase.value === 'done') return 100
    if (!totalBytes.value) return 0
    return Math.min(99, Math.round((loadedBytes.value / totalBytes.value) * 100))
  })
  const progressText = computed(() => {
    if (phase.value === 'resolving') return '解析链接中'
    if (phase.value === 'downloading') {
      const indexText = totalCount.value > 1 ? `${currentIndex.value}/${totalCount.value} · ` : ''
      if (currentUsesNativeDownload.value) return `${indexText}交给浏览器下载`
      const percentText = totalBytes.value ? `${progressPercent.value}%` : '下载中'
      return `${indexText}${percentText}`
    }
    if (phase.value === 'done') {
      if (nativeDownloadCount.value) {
        return totalCount.value > 1 ? `已触发 ${totalCount.value} 个文件` : '已开始下载'
      }
      return totalCount.value > 1 ? `已完成 ${totalCount.value} 个文件` : '下载完成'
    }
    return ''
  })
  const progressDetail = computed(() => {
    if (phase.value === 'downloading') return currentFilename.value
    return resultText.value
  })

  async function pasteFromClipboard() {
    error.value = ''

    try {
      const text = await navigator.clipboard.readText()
      if (text.trim()) linkText.value = text.trim()
    } catch {
      error.value = '无法读取剪切板，请手动粘贴'
    }
  }

  async function downloadItem(item: MediaItem, index = 1, total = 1) {
    if (downloadingUrl.value) throw new Error('已有下载任务进行中')

    downloadingUrl.value = item.download_url
    error.value = ''
    currentIndex.value = index
    totalCount.value = total
    currentFilename.value = item.filename
    loadedBytes.value = 0
    totalBytes.value = item.size || 0
    currentUsesNativeDownload.value = isVideoItem(item)
    phase.value = 'downloading'

    try {
      if (currentUsesNativeDownload.value) {
        triggerNativeDownload(item)
        nativeDownloadCount.value += 1
        await wait(NATIVE_DOWNLOAD_DELAY)
        return
      }

      const response = await fetch(attachmentUrl(item))
      if (!response.ok) throw new Error('下载失败')

      const length = Number(response.headers.get('content-length') || 0)
      if (length > 0) totalBytes.value = length

      const blob = response.body
        ? await readResponseBlob(response)
        : await response.blob()

      saveBlob(blob, item.filename)
    } finally {
      downloadingUrl.value = ''
    }
  }

  async function extractMedia() {
    if (!canSubmit.value) return

    loading.value = true
    error.value = ''
    result.value = null
    phase.value = 'resolving'
    currentIndex.value = 0
    totalCount.value = 0
    currentFilename.value = ''
    loadedBytes.value = 0
    totalBytes.value = 0
    nativeDownloadCount.value = 0
    currentUsesNativeDownload.value = false

    const controller = new AbortController()
    const timeoutId = window.setTimeout(() => controller.abort(), 90_000)

    try {
      const response = await fetch(`${apiBase}/api/resolve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: controller.signal,
        body: JSON.stringify({ url: linkText.value.trim() })
      })

      const payload = await response.json().catch(() => null)
      if (!response.ok) {
        throw new Error(payload?.detail?.message || payload?.message || '提取失败')
      }

      result.value = payload as ExtractResponse
      const items = result.value.items
      if (!items.length) throw new Error('没有找到可下载的图片或视频')

      for (const [index, item] of items.entries()) {
        await downloadItem(item, index + 1, items.length)
      }
      phase.value = 'done'
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === 'AbortError') {
        error.value = '提取超时，请稍后再试'
      } else {
        error.value = caught instanceof Error ? caught.message : '提取失败'
      }
      phase.value = 'idle'
    } finally {
      window.clearTimeout(timeoutId)
      loading.value = false
    }
  }

  async function readResponseBlob(response: Response) {
    const reader = response.body?.getReader()
    if (!reader) return response.blob()

    const chunks: BlobPart[] = []
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      if (value) {
        const chunk = new Uint8Array(value.byteLength)
        chunk.set(value)
        chunks.push(chunk.buffer as ArrayBuffer)
        loadedBytes.value += value.byteLength
      }
    }
    return new Blob(chunks, {
      type: response.headers.get('content-type') || 'application/octet-stream'
    })
  }

  function saveBlob(blob: Blob, filename: string) {
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 1200)
  }

  function triggerNativeDownload(item: MediaItem) {
    const link = document.createElement('a')
    link.href = attachmentUrl(item)
    link.download = item.filename
    link.rel = 'noopener'
    document.body.appendChild(link)
    link.click()
    link.remove()
  }

  function isVideoItem(item: MediaItem) {
    const value = `${item.kind} ${item.mime_type} ${item.filename} ${item.download_url}`.toLowerCase()
    return (
      item.kind === 'video' ||
      item.mime_type.startsWith('video/') ||
      /\.(mp4|mov|m4v|webm|mkv)(?:$|\?)/i.test(item.filename) ||
      value.includes('/aweme/v1/play') ||
      value.includes('mime_type=video') ||
      value.includes('sns-video') ||
      value.includes('video.twimg.com')
    )
  }

  function wait(duration: number) {
    return new Promise((resolve) => window.setTimeout(resolve, duration))
  }

  return {
    canSubmit,
    currentFilename,
    currentIndex,
    downloadItem,
    downloadingUrl,
    error,
    extractMedia,
    hasResult,
    linkText,
    loading,
    pasteFromClipboard,
    phase,
    progressDetail,
    progressPercent,
    progressText,
    result,
    resultText,
    totalCount,
    visibleItems
  }
}
