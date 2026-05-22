import { createApp } from 'vue'
import { Button, Field } from 'vant'
import 'vant/es/button/style'
import 'vant/es/field/style'
import 'vant/es/image-preview/style'
import App from '@/App.vue'
import { router } from '@/router'
import '@/styles.css'

createApp(App)
  .use(router)
  .use(Button)
  .use(Field)
  .mount('#app')
