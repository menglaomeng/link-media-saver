import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  base: process.env.VITE_BASE_PATH || '/',
  plugins: [vue()],
  resolve: {
    alias: {
      '@': new URL('./src', import.meta.url).pathname
    }
  },
  server: {
    port: 5173,
    headers: {
      'Permissions-Policy': 'unload=(self)'
    },
    proxy: {
      '/api': 'http://localhost:8000',
      '/media': 'http://localhost:8000'
    }
  },
  preview: {
    headers: {
      'Permissions-Policy': 'unload=(self)'
    }
  }
})
