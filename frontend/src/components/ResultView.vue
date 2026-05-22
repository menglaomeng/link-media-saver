<script setup lang="ts">
import { AlertTriangle } from 'lucide-vue-next'
import MediaCard from '@/components/MediaCard.vue'
import type { ExtractResponse, MediaItem } from '@/types/media'

defineProps<{
  downloadingUrl: string
  items: MediaItem[]
  result: ExtractResponse | null
  resultClass: string
  resultText: string
}>()

const emit = defineEmits<{
  download: [item: MediaItem]
  preview: [item: MediaItem]
}>()
</script>

<template>
  <section class="result" :class="resultClass">
    <div v-if="result?.warnings.length" class="notice warning">
      <AlertTriangle :size="17" />
      <div>
        <p v-for="warning in result.warnings" :key="warning">{{ warning }}</p>
      </div>
    </div>

    <p v-if="resultText" class="caption-text">{{ resultText }}</p>

    <div v-if="items.length" class="media-grid">
      <MediaCard
        v-for="item in items"
        :key="item.download_url"
        :item="item"
        :is-downloading="downloadingUrl === item.download_url"
        @download="emit('download', $event)"
        @preview="emit('preview', $event)"
      />
    </div>
  </section>
</template>
