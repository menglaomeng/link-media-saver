<script setup lang="ts">
import { Download, Loader2 } from 'lucide-vue-next'
import type { MediaItem } from '@/types/media'
import { absoluteMediaUrl } from '@/utils/mediaUrl'

defineProps<{
  isDownloading: boolean
  item: MediaItem
}>()

const emit = defineEmits<{
  download: [item: MediaItem]
  preview: [item: MediaItem]
}>()
</script>

<template>
  <article class="media-card" :class="`is-${item.kind}`">
    <button
      v-if="item.kind === 'image'"
      class="preview preview-button"
      type="button"
      aria-label="查看大图"
      @click="emit('preview', item)"
    >
      <img :src="absoluteMediaUrl(item.download_url)" :alt="item.filename" />
    </button>

    <div v-else class="preview">
      <video
        v-if="item.kind === 'video'"
        controls
        preload="metadata"
        playsinline
      >
        <source :src="absoluteMediaUrl(item.download_url)" :type="item.mime_type || 'video/mp4'" />
      </video>
      <span v-else class="file-fallback">{{ item.kind }}</span>
    </div>

    <div class="actions">
      <button
        class="download-button"
        type="button"
        :disabled="isDownloading"
        aria-label="下载"
        @click.stop="emit('download', item)"
      >
        <Loader2 v-if="isDownloading" class="spin" :size="14" />
        <Download v-else :size="14" />
        <span>{{ isDownloading ? '下载中' : '下载' }}</span>
      </button>
    </div>
  </article>
</template>
