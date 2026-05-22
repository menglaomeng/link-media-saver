<script setup lang="ts">
import { AlertTriangle } from 'lucide-vue-next'
import DownloadProgress from '@/components/DownloadProgress.vue'
import ExtractForm from '@/components/ExtractForm.vue'
import { useMediaExtractor } from '@/composables/useMediaExtractor'

defineOptions({
  name: 'MediaExtractorPage'
})

const {
  canSubmit,
  error,
  extractMedia,
  hasResult,
  linkText,
  loading,
  pasteFromClipboard,
  progressDetail,
  progressPercent,
  progressText
} = useMediaExtractor()
</script>

<template>
  <main class="shell">
    <section class="workspace">
      <header class="hero-copy">
        <h1>粘贴链接，直接下载</h1>
        <p>不展示预览，解析完成后保存到本地。</p>
      </header>

      <div class="download-card" :class="{ active: hasResult }">
        <ExtractForm
          v-model="linkText"
          :can-submit="canSubmit"
          :loading="loading"
          @paste="pasteFromClipboard"
          @submit="extractMedia"
        />

        <div v-if="error" class="notice error">
          <AlertTriangle :size="17" />
          <span>{{ error }}</span>
        </div>

        <DownloadProgress
          :detail="progressDetail"
          :percent="progressPercent"
          :text="progressText"
          :visible="hasResult"
        />
      </div>
    </section>
  </main>
</template>
