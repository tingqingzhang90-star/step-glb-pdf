// 前后端共用样式配置加载器(从 cad_viewer_style.json 读取)
// 前端: SVG 用 px(屏幕像素,浏览器已按 non-scaling-stroke 处理)
// 改 cad_viewer_style.json 后,前端需刷新生效

import config from '../../../cad_viewer_style.json'

export function useStyleConfig() {
  // 1) 写 CSS 自定义属性到 :root,样式表里用 var(--xxx)
  function applyToRoot(doc = document) {
    const root = doc.documentElement
    root.style.setProperty('--edge-visible-stroke', config.edge.visible.stroke_px)
    root.style.setProperty('--edge-hidden-stroke', config.edge.hidden.stroke_px)
    root.style.setProperty('--dim-line-stroke', config.dim.line.stroke_px)
    root.style.setProperty('--dim-ext-stroke', config.dim.ext.stroke_px)
    root.style.setProperty('--dim-text-size', `${config.dim.text.font_px}px`)
    root.style.setProperty('--center-mark-stroke', config.center_mark.stroke_px)
    root.style.setProperty('--frame-stroke', config.frame.stroke_px)
    root.style.setProperty('--title-block-stroke', config.title_block.stroke_px)
  }

  // 2) 返回给 JS 计算用(箭头尺寸等)
  return {
    config,
    arrowLenPx: config.dim.arrow.len_px,
    arrowHalfPx: config.dim.arrow.half_px,
    applyToRoot
  }
}
