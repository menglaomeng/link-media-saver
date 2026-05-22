<script setup lang="ts">
import { useRoute } from "vue-router";

const route = useRoute();
</script>

<template>
  <router-view v-slot="{ Component }">
    <component :is="Component" :key="route.name" />
  </router-view>
</template>
