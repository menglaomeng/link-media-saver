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
    <van-field
      :model-value="modelValue"
      class="link-field"
      placeholder="粘贴作品链接"
      :border="false"
      aria-label="分享链接"
      @update:model-value="emit('update:modelValue', String($event))"
    >
      <template #button>
        <button class="paste-button" type="button" @click="emit('paste')">
          粘贴
        </button>
      </template>
    </van-field>

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
