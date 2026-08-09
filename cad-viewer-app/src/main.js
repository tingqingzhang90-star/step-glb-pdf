import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import { initializeCadViewer } from '@mlightcad/cad-viewer'
import App from './App.vue'
import './style.css'

// 初始化 cad-viewer 引擎
initializeCadViewer()

const app = createApp(App)
app.use(ElementPlus)
app.mount('#app')
