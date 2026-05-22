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
      <div class="download-card" :class="{ active: hasResult }">
        <header class="card-copy">
          <h1>链接素材下载</h1>
          <p>支持主流平台作品链接，解析后按顺序保存</p>
        </header>

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
