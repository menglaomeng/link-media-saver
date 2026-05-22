<script setup lang="ts">
defineProps<{
  canSubmit: boolean
  loading: boolean
  modelValue: string
}>()

const emit = defineEmits<{
  paste: []
  submit: []
  'update:modelValue': [value: string]
}>()
</script>

<template>
  <form class="extract-form" @submit.prevent="emit('submit')">
    <div class="form-head">
      <span>分享链接</span>
      <button class="paste-button" type="button" @click="emit('paste')">
        粘贴
      </button>
    </div>

    <van-field
      :model-value="modelValue"
      class="link-field"
      type="textarea"
      placeholder="https://example.com/share/..."
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
      提取并下载
    </van-button>

    <p class="form-note">支持抖音、小红书、得物、X 等公开作品链接。</p>
  </form>
</template>
