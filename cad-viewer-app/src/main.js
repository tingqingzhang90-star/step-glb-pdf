import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import { i18n } from '@mlightcad/cad-viewer'
import App from './App.vue'
import './style.css'

// 使用 cad-viewer 包导出的 i18n 实例（已通过 mergeLocaleMessage 加载完整的 zh/en 等多语言翻译消息）。
//
// 根本原因（之前的报错）：
//   main.js 之前用 createI18n({ messages: { zh: {}, en: {} } }) 创建了一个空 i18n 实例，
//   覆盖了 cad-viewer 包自带的、含完整翻译的 i18n 实例，导致界面所有翻译 key 查不到文本，
//   显示原始 key（如 main.ribbon.tab.insert、main.toolPalette.missingResources.file 等），
//   控制台大量 [intlify] Not found 'xxx' key 警告。
//
// 根本解决方案：
//   按 cad-viewer README 的正确用法，直接 import { i18n } from '@mlightcad/cad-viewer'，
//   使用包导出的、已配置好的 i18n 实例（包含完整 zh/en 翻译），不再创建空 i18n。
//   - 不修改 node_modules 中的任何文件
//   - 不再依赖 data-model-shim.js 中的逻辑（保留 shim 仅用于补充缺失导出）
const app = createApp(App)
app.use(i18n)
app.use(ElementPlus)
app.mount('#app')
