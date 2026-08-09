/**
 * @mlightcad/data-model 的 shim 模块
 *
 * 背景：
 *   @mlightcad/cad-simple-viewer@1.5.9 从 @mlightcad/data-model@1.12.4 导入
 *   AcDbFontNameCollector，但该类在 data-model@1.12.4 中不存在
 *   （mlightcad 发布版本不匹配 bug，data-model 已是最新版无更高版本可升）。
 *   Vite 8 的 Rolldown 依赖优化器对 missing-export 直接报错。
 *
 * 方案：
 *   本文件 re-export 真实 data-model 的全部命名导出（用相对路径指向
 *   node_modules 避免被 resolveId alias 拦截形成循环），并补充一个
 *   功能性的 AcDbFontNameCollector 空实现。
 *
 *   vite.config.js 中的 resolveId 把对 '@mlightcad/data-model' 裸导入
 *   重定向到本文件（同时注册为 Vite 插件和 Rolldown 依赖优化插件）。
 *
 *   AcDbFontNameCollector 在 cad-simple-viewer 的 getFonts() 中被调用，
 *   用于收集 DXF 字体信息；空实现返回空集合，不影响 DXF 视图加载与标注。
 */

// 用相对路径导入真实 data-model，绕过 resolveId 对裸导入的拦截
export * from '../node_modules/@mlightcad/data-model/lib/index.js'

/**
 * AcDbFontNameCollector 空实现
 * 真实类用于遍历 DXF 实体收集使用的字体，这里返回空集合
 */
export class AcDbFontNameCollector {
  constructor(options) {
    this._options = options || {}
  }

  /**
   * 收集数据库中使用的字体信息
   * @returns {{ fonts: Map<string, object>, used: Set<string> }}
   */
  collect(entities, callbacks) {
    return { fonts: new Map(), used: new Set() }
  }
}
