import { createRouter, createWebHistory } from 'vue-router'
import MediaExtractorPage from '@/pages/MediaExtractorPage.vue'

export const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'MediaExtractorPage',
      component: MediaExtractorPage
    }
  ]
})
