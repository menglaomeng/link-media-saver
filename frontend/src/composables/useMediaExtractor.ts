import { computed, ref } from 'vue'
import type { ExtractResponse, MediaItem } from '@/types/media'
import { apiBase, attachmentUrl } from '@/utils/mediaUrl'

type DownloadPhase = 'idle' | 'resolving' | 'downloading' | 'done'

const BROWSER_DOWNLOAD_DELAY = 600

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
  const browserDownloadCount = ref(0)

  const canSubmit = computed(() => linkText.value.trim().length > 0 && !loading.value)
  const hasResult = computed(() => phase.value !== 'idle')
  const visibleItems = computed(() => result.value?.items ?? [])
  const resultText = computed(() => {
    const title = result.value?.title?.trim() ?? ''
    return title.replace(/\s+-\s+(抖音|小红书|Douyin|XiaoHongShu)$/i, '').trim()
  })
  const progressPercent = computed(() => {
    if (phase.value === 'done') return 100
    if (phase.value !== 'downloading' || !totalCount.value) return 0
    return Math.min(99, Math.round((currentIndex.value / totalCount.value) * 100))
  })
  const progressText = computed(() => {
    if (phase.value === 'resolving') return '解析链接中'
    if (phase.value === 'downloading') {
      const indexText = totalCount.value > 1 ? `${currentIndex.value}/${totalCount.value} · ` : ''
      return `${indexText}交给浏览器下载`
    }
    if (phase.value === 'done') {
      return browserDownloadCount.value > 1 ? `已触发 ${browserDownloadCount.value} 个文件` : '已开始下载'
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
    phase.value = 'downloading'

    try {
      triggerBrowserDownload(item)
      browserDownloadCount.value += 1
      await wait(BROWSER_DOWNLOAD_DELAY)
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
    browserDownloadCount.value = 0

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

  function triggerBrowserDownload(item: MediaItem) {
    const link = document.createElement('a')
    link.href = attachmentUrl(item)
    link.download = item.filename
    link.rel = 'noopener'
    document.body.appendChild(link)
    link.click()
    link.remove()
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
