import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
// shim 文件绝对路径，re-export 真实 data-model + 补充 AcDbFontNameCollector
const SHIM_PATH = path.resolve(__dirname, 'src/data-model-shim.js')

/**
 * 创建 resolveId 插件对象（Vite 插件与 Rolldown 依赖优化插件共用同一逻辑）
 *
 * 背景：
 *   @mlightcad/cad-simple-viewer@1.5.9 从 @mlightcad/data-model@1.12.4 导入
 *   AcDbFontNameCollector，但该类在 data-model@1.12.4 中根本不存在
 *   （mlightcad 发布版本不匹配 bug，且 data-model 已是最新版无更高版本可升）。
 *
 *   Vite 8 弃用 esbuild 改用 Rolldown 做依赖优化，Rolldown 对 missing-export
 *   直接报错（不像 esbuild 可用 logOverride 降级），导致 dev server 启动失败。
 *
 * 方案：
 *   拦截对 '@mlightcad/data-model' 的裸导入，重定向到 src/data-model-shim.js。
 *   shim 文件用相对路径 re-export 真实 data-model 全部命名导出（绕过拦截避免
 *   循环），并补充功能性的 AcDbFontNameCollector 空实现。
 *
 *   - 不修改 node_modules 中的任何文件
 *   - 同时注册为 Vite 插件（运行时模块解析）和 Rolldown 插件（依赖优化阶段），
 *     因为 Vite 插件的 resolveId 不在依赖优化阶段生效
 */
function createPatchDataModelPlugin() {
  const PKG = '@mlightcad/data-model'
  return {
    name: 'patch-data-model-missing-export',
    resolveId(source, importer) {
      // 只拦截裸导入 '@mlightcad/data-model'，重定向到 shim 文件
      // shim 自身用相对路径 '../node_modules/...' 导入真实模块，不会被拦截
      if (source === PKG) {
        return SHIM_PATH
      }
      return null
    }
  }
}

/**
 * Vite/Rolldown 插件：为未安装的可选 peer dep 提供空模块
 *
 * 背景：
 *   @mlightcad/cad-viewer@1.5.9 把 4 个插件标记为 optional peer dep
 *   (cad-agent-plugin / cad-html-plugin / cad-pdf-plugin / cad-svg-plugin)，
 *   这 4 个包均未安装。
 *
 *   cad-viewer 对它们的引用有两种方式：
 *   1. 静态 import（第12-14行）：
 *        import { registerLazyHtmlPlugin } from "@mlightcad/cad-html-plugin/register";
 *        import { registerLazyPdfPlugin } from "@mlightcad/cad-pdf-plugin/register";
 *        import { registerLazySvgPlugin } from "@mlightcad/cad-svg-plugin/register";
 *      → 直接解析包路径，未安装时构建报错
 *   2. 动态 import()（第32800, 42596-42597, 47986-47987行）：
 *        await import("@mlightcad/cad-agent-plugin/style.css");
 *      → Vite 转换为 __vite-optional-peer-dep: 协议，但 .css 子路径有 bug
 *
 *   两种方式都需要拦截，返回包含被解构命名导出的空模块。
 *   cad-viewer 中对空模块的调用都是注册函数（无副作用）或在 try/catch 中，
 *   不会触发运行时错误。
 *
 *   同时注册为 Vite 插件（运行时）和 Rolldown 依赖优化插件（预构建阶段）。
 */
function resolveOptionalPeerDeps() {
  const PREFIX = '__vite-optional-peer-dep:'
  const VIRTUAL_PREFIX = '\0optional-peer-dep:'

  // 4 个未安装的可选 peer dep 包名前缀
  const OPTIONAL_PKGS = [
    '@mlightcad/cad-agent-plugin',
    '@mlightcad/cad-html-plugin',
    '@mlightcad/cad-pdf-plugin',
    '@mlightcad/cad-svg-plugin'
  ]

  // 各包/子路径需要提供的命名导出（cad-viewer 解构用的名称）
  const EXPORTS = {
    '@mlightcad/cad-agent-plugin': [
      'AgentChatPanel', 'setAgentPaletteOpener',
      'mergeAgentI18nIntoVueI18n', 'registerLazyAgentPlugin'
    ],
    '@mlightcad/cad-agent-plugin/register': ['registerLazyAgentPlugin'],
    '@mlightcad/cad-agent-plugin/style.css': null, // 空 CSS
    '@mlightcad/cad-html-plugin': ['AcApHtmlConvertor', 'resolveAcApHtmlExportOptions'],
    '@mlightcad/cad-html-plugin/register': ['registerLazyHtmlPlugin'],
    '@mlightcad/cad-pdf-plugin': ['AcApPdfConvertor', 'resolveAcApPdfExportOptions'],
    '@mlightcad/cad-pdf-plugin/register': ['registerLazyPdfPlugin'],
    '@mlightcad/cad-svg-plugin': ['AcApSvgConvertor', 'resolveAcApSvgExportOptions'],
    '@mlightcad/cad-svg-plugin/register': ['registerLazySvgPlugin']
  }

  function normalizeDepPath(depPath) {
    for (const key of Object.keys(EXPORTS)) {
      if (depPath === key || depPath.startsWith(key + ':')) {
        return key
      }
    }
    return depPath
  }

  // 生成空 ESM 模块代码
  function buildEmptyModule(depPath) {
    const normalizedDepPath = normalizeDepPath(depPath)
    // .css → 空 CSS
    if (normalizedDepPath.includes('.css')) return ''
    const names = EXPORTS[normalizedDepPath]
    if (!names) return ''
    // 生成 const + export 声明，函数返回 undefined / null
    const lines = names.map(
      (n) => `const ${n} = ${n === 'AgentChatPanel' ? 'null' : '() => {}'};`
    )
    lines.push(`export { ${names.join(', ')} };`)
    lines.push(`export default { ${names.join(', ')} };`)
    return lines.join('\n')
  }

  return {
    name: 'resolve-optional-peer-deps',
    resolveId(id) {
      if (typeof id !== 'string') return null

      // 1. 拦截 __vite-optional-peer-dep: 协议（动态 import 的可选 peer dep）
      if (id.startsWith(PREFIX)) {
        const rest = id.slice(PREFIX.length)
        // 协议格式: __vite-optional-peer-dep:<dep-path>:<importer>
        // dep-path 可能含 ':'（Windows 路径），取 importer 之前的部分
        // 但简单处理：整个 rest 就是 dep-path
        return VIRTUAL_PREFIX + rest
      }

      // 2. 拦截直接的包路径导入（静态 import 的可选 peer dep）
      for (const pkg of OPTIONAL_PKGS) {
        if (id === pkg || id.startsWith(pkg + '/')) {
          return VIRTUAL_PREFIX + id
        }
      }
      return null
    },
    load(id) {
      if (typeof id !== 'string' || !id.startsWith(VIRTUAL_PREFIX)) return null
      const depPath = id.slice(VIRTUAL_PREFIX.length)
      return buildEmptyModule(depPath)
    }
  }
}

export default defineConfig({
  plugins: [vue(), createPatchDataModelPlugin(), resolveOptionalPeerDeps()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
      '@mlightcad/data-model': SHIM_PATH
    }
  },
  build: {
    cssMinify: false
  },
  server: {
    host: true,
    port: 5174,
    // host:true 让 dev server 监听所有网卡,手机通过电脑局域网 IP 才能访问;
    // allowedHosts 放开为 true,否则手机用 IP 访问会因 Host 头不匹配被 Vite 拦成 403
    allowedHosts: true,
    // 允许 dev server 读取项目根之外的 cad_viewer_style.json
    // (前后端共用样式配置,见 docs/前后端显示样式一致方案.md)
    fs: {
      allow: [path.resolve(__dirname, '..')]
    },
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:5001',
        changeOrigin: true
      }
    }
  },
  preview: {
    host: true,
    port: 5174,
    allowedHosts: true
  },
  optimizeDeps: {
    // Vite 8 用 Rolldown 做依赖优化，Vite 插件的 resolveId 不在此阶段生效，
    // 需通过 rolldownOptions.plugins 注入 Rolldown 插件：
    //   - patchDataModel: 补充 data-model 缺失的 AcDbFontNameCollector 导出
    //   - resolveOptionalPeerDeps: 为未安装的可选 peer dep 提供空模块
    rolldownOptions: {
      plugins: [createPatchDataModelPlugin(), resolveOptionalPeerDeps()]
    }
  }
  // 注意：Vite 8 弃用 esbuild 改用 Rolldown 做依赖优化，
  // 原 optimizeDeps.esbuildOptions.logOverride 已失效且被移除。
  // missing-export 问题改由 createPatchDataModelPlugin 在源头解决。
})
