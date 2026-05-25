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
  progressDetail,
  progressPercent,
  progressText
} = useMediaExtractor()
</script>

<template>
  <main class="shell">
    <section class="workspace">
      <div class="brand-row" aria-label="LinkDown">
        <span class="brand-mark" aria-hidden="true">
          <span></span>
        </span>
        <span class="brand-word">LinkDown</span>
      </div>

      <header class="hero-copy">
        <h1>粘贴链接即可下载</h1>
        <p>视频和图片，直接保存。</p>
      </header>

      <div class="download-card" :class="{ active: hasResult }">
        <ExtractForm
          v-model="linkText"
          :can-submit="canSubmit"
          :loading="loading"
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

      <p class="fine-print">公开链接可用</p>
    </section>
  </main>
</template>
