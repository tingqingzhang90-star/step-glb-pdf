// 所见即所得导出:克隆画布 SVG → 剔除 UI 层 → 内联样式 → 高分辨率光栅化 → jsPDF。
// 不再用 jsPDF 重画几何(坐标换算易错),画布上是什么样,PDF 就是什么样。
import { jsPDF } from 'jspdf'

// 仅用于交互、不应出现在图纸上的层(克隆后整层删除)
const UI_LAYER_SELECTOR = [
  '.alignment-guides',      // 视图拖拽对齐线
  '.dim-hit-layer',         // 标注命中层(标注工具激活时)
  '.dim-highlight',         // 边线 hover/选中高亮
  '.dim-preview',           // 标注落位预览
  '.palette-drag-preview',  // 调色板拖拽预览
  '.dim-hit-stroke',        // 加宽的透明命中线
  '.dim-extension-hit',     // 选中标注的延展手柄
  '.table-snap-guides',     // 表格吸附引导线
  'foreignObject'           // 单元格编辑输入框
].join(',')

/** 把 :root 上的 CSS 变量(--edge-visible-stroke 等)收集成 style 字符串。
 *  SVG 以 <img> 方式光栅化时读不到 document 的样式,必须带进克隆里。 */
function collectRootCssVars() {
  const cs = getComputedStyle(document.documentElement)
  const vars = []
  for (let i = 0; i < cs.length; i++) {
    const prop = cs[i]
    if (prop.startsWith('--')) {
      const v = cs.getPropertyValue(prop).trim()
      if (v) vars.push(`${prop}: ${v}`)
    }
  }
  return vars.join('; ')
}

/** 收集页面上"克隆 SVG 里实际用到"的 CSS 规则。
 *  样式都在 <style> 里(类选择器 + CSS 变量),SVG 图片化后外部样式失效,需内联。 */
function collectCssRules(clone) {
  const classSet = new Set()
  const addClasses = (s) => String(s || '').split(/\s+/).forEach(c => c && classSet.add(c))
  addClasses(clone.getAttribute('class'))
  clone.querySelectorAll('[class]').forEach(el => addClasses(el.getAttribute('class')))
  if (!classSet.size) return ''

  const rules = []
  for (const sheet of Array.from(document.styleSheets)) {
    let cssRules
    try { cssRules = sheet.cssRules } catch (e) { continue } // 跨域样式表跳过
    for (const rule of Array.from(cssRules || [])) {
      const sel = rule.selectorText || ''
      if (!sel) continue
      for (const c of classSet) {
        if (sel.includes('.' + c)) { rules.push(rule.cssText); break }
      }
    }
  }
  return rules.join('\n')
}

/** 视图组带 scale(如 1:2),去掉 vector-effect 后线宽会被缩放。
 *  读原始元素的计算样式(浏览器实际用的 px 值),除以视图缩放写回克隆,
 *  保证任何比例的视图,打印线宽都等于样式配置的 mm 值。 */
function compensateStrokeWidths(svgEl, clone) {
  const origViews = svgEl.querySelectorAll('.placed-view')
  const cloneViews = clone.querySelectorAll('.placed-view')
  origViews.forEach((ov, i) => {
    const transform = cloneViews[i].getAttribute('transform') || ''
    const m = transform.match(/scale\(\s*([\d.]+)\s*\)/)
    const s = m ? parseFloat(m[1]) : 1
    if (!Number.isFinite(s) || Math.abs(s - 1) < 1e-6) return
    const oEls = ov.querySelectorAll('line, polyline, circle')
    const cEls = cloneViews[i].querySelectorAll('line, polyline, circle')
    oEls.forEach((oe, j) => {
      const ce = cEls[j]
      if (!ce) return
      const v = parseFloat(getComputedStyle(oe).strokeWidth)
      if (!Number.isFinite(v) || v === 0) return
      ce.setAttribute('stroke-width', String(v / s))
    })
  })
}

/**
 * 所见即所得导出 PDF。
 * @param {SVGElement} svgEl    画布 SVG 元素(模板 ref svgRef)
 * @param {number} sheetWidthMm 图纸宽(mm,如 A3=420)
 * @param {number} sheetHeightMm 图纸高(mm)
 * @param {string} fileName     保存文件名
 * @param {number} dpi          光栅化精度,默认 300(打印级)
 */
export async function exportSheetScreenshotPdf({
  svgEl, sheetWidthMm, sheetHeightMm, fileName, dpi = 300
}) {
  if (!svgEl) throw new Error('画布未就绪')

  const pxPerMm = dpi / 25.4
  const pxW = Math.ceil(sheetWidthMm * pxPerMm)
  const pxH = Math.ceil(sheetHeightMm * pxPerMm)

  // 1) 克隆并清理
  const clone = svgEl.cloneNode(true)
  clone.querySelectorAll(UI_LAYER_SELECTOR).forEach(el => el.remove())
  // 卡片阴影等展示样式不要;换成 root 的 CSS 变量
  clone.removeAttribute('style')
  const rootVars = collectRootCssVars()
  if (rootVars) clone.setAttribute('style', rootVars)

  // 2) 线宽补偿(必须在移除 vector-effect 前读原始元素的计算样式)
  compensateStrokeWidths(svgEl, clone)
  // 300dpi 大图下 1px 发丝线不可见,移除后线宽按 mm 真实缩放
  clone.querySelectorAll('[vector-effect]').forEach(el => el.removeAttribute('vector-effect'))

  // 3) 导出尺寸 + 内联 CSS
  clone.setAttribute('width', pxW)
  clone.setAttribute('height', pxH)
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
  const cssText = collectCssRules(clone)
  if (cssText) {
    const styleEl = document.createElementNS('http://www.w3.org/2000/svg', 'style')
    styleEl.textContent = cssText
    clone.insertBefore(styleEl, clone.firstChild)
  }

  // 4) SVG → Image → Canvas(300dpi)
  const svgText = new XMLSerializer().serializeToString(clone)
  const blob = new Blob([svgText], { type: 'image/svg+xml;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  let dataUrl
  try {
    const img = await new Promise((resolve, reject) => {
      const im = new Image()
      im.onload = () => resolve(im)
      im.onerror = () => reject(new Error('画布光栅化失败(SVG 解析错误)'))
      im.src = url
    })
    const canvas = document.createElement('canvas')
    canvas.width = pxW
    canvas.height = pxH
    const ctx = canvas.getContext('2d')
    ctx.fillStyle = '#ffffff'
    ctx.fillRect(0, 0, pxW, pxH)
    ctx.drawImage(img, 0, 0, pxW, pxH)
    dataUrl = canvas.toDataURL('image/png')
  } finally {
    URL.revokeObjectURL(url)
  }

  // 5) 贴进与图纸同尺寸的 PDF 页
  const doc = new jsPDF({
    orientation: sheetWidthMm >= sheetHeightMm ? 'landscape' : 'portrait',
    unit: 'mm',
    format: [sheetWidthMm, sheetHeightMm],
    compress: true
  })
  doc.addImage(dataUrl, 'PNG', 0, 0, sheetWidthMm, sheetHeightMm)
  doc.save(fileName || 'drawing.pdf')
}
