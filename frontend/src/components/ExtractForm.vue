<script setup lang="ts">
defineProps<{
  canSubmit: boolean
  loading: boolean
  modelValue: string
}>()

const emit = defineEmits<{
  submit: []
  'update:modelValue': [value: string]
}>()
</script>

<template>
  <form class="extract-form" @submit.prevent="emit('submit')">
    <van-field
      :model-value="modelValue"
      class="link-field"
      type="textarea"
      placeholder="粘贴分享链接..."
      :rows="3"
      :border="false"
      aria-label="分享链接"
      @update:model-value="emit('update:modelValue', String($event))"
    />

    <van-button
      class="primary-button"
      type="primary"
      block
      native-type="submit"
      :loading="loading"
      loading-text="下载中"
      :disabled="!canSubmit"
      aria-label="提取"
    >
      下载
    </van-button>
  </form>
</template>
