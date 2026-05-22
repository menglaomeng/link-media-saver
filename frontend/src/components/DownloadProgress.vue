<script setup lang="ts">
defineProps<{
  detail: string
  percent: number
  text: string
  visible: boolean
}>()
</script>

<template>
  <section v-if="visible" class="download-progress">
    <div class="progress-head">
      <span>{{ text }}</span>
      <strong v-if="percent">{{ percent }}%</strong>
    </div>
    <div class="progress-track" aria-hidden="true">
      <span class="progress-bar" :style="{ width: `${percent || 16}%` }" />
    </div>
    <p v-if="detail" class="progress-detail">{{ detail }}</p>
  </section>
</template>
