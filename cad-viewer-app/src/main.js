import { createApp } from 'vue'
import { createI18n } from 'vue-i18n'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import App from './App.vue'
import './style.css'

const i18n = createI18n({
  legacy: false,
  locale: 'zh',
  messages: {
    zh: {}
  }
})

const app = createApp(App)
app.use(i18n)
app.use(ElementPlus)
app.mount('#app')
