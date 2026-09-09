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

// 这些 CSS 变量控制线宽,导出时统一按 lineWeight 放大,抵消 300dpi 重采样到屏幕
// 时抗锯齿灰边造成的"发虚"感。
const STROKE_VARS = [
  '--edge-visible-stroke',
  '--edge-hidden-stroke',
  '--dim-line-stroke',
  '--dim-ext-stroke',
  '--center-mark-stroke',
  '--frame-stroke',
  '--title-block-stroke'
]

/** 把 :root 上的 CSS 变量收集成 style 字符串,stroke_px 变量按 lineWeight 放大。
 *  SVG 以 <img> 方式光栅化时读不到 document 的样式,必须带进克隆里。 */
function collectRootCssVars(lineWeight) {
  const cs = getComputedStyle(document.documentElement)
  const vars = []
  for (let i = 0; i < cs.length; i++) {
    const prop = cs[i]
    if (prop.startsWith('--')) {
      let v = cs.getPropertyValue(prop).trim()
      if (!v) continue
      if (lineWeight !== 1 && STROKE_VARS.includes(prop) && /^[\d.]+$/.test(v)) {
        v = String(parseFloat(v) * lineWeight)
      }
      vars.push(`${prop}: ${v}`)
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
 *  读原始元素的计算样式(浏览器实际用的 px 值)乘以 lineWeight 再除以视图缩放,
 *  用 !important 内联样式写回克隆,保证任何比例的视图打印线宽一致。 */
function compensateStrokeWidths(svgEl, clone, lineWeight) {
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
      const desired = (v * lineWeight) / s
      ce.style.setProperty('stroke-width', `${desired.toFixed(5)}px`, 'important')
    })
  })
}

/** 把单元格里的 <image href="/api/symbols/xxx.svg">(或 data: SVG)内联成真实 <svg> 节点。
 *  原因:导出时外层 SVG 以 <img> 方式加载,浏览器安全静态模式不会去抓取内部
 *  <image> 引用的外部资源;即便能抓,img.onload 也只等外层 SVG、不等子图加载完,
 *  drawImage 时符号还是空白(这正是"导入源文件后导出符号消失"的根因——导入场景的
 *  符号本会话未缓存,竞态必现;非导入场景碰巧缓存命中才画出来)。
 *  直接把符号 SVG 内容嵌进克隆图,导出结果自包含、必然可见,且不再依赖服务器在线。 */
async function inlineSymbolImages(clone) {
  const imgs = Array.from(clone.querySelectorAll('image'))
  if (!imgs.length) return
  const cache = new Map()
  const NS = 'http://www.w3.org/2000/svg'
  for (const img of imgs) {
    const href = img.getAttribute('href') || img.getAttribute('xlink:href')
    if (!href) continue
    const isSymbol = href.includes('/api/symbols/') || href.startsWith('data:image/svg')
    if (!isSymbol) continue
    let svgText = null
    try {
      if (href.startsWith('data:')) {
        const comma = href.indexOf(',')
        const meta = href.slice(5, comma)
        const data = href.slice(comma + 1)
        svgText = meta.includes('base64') ? atob(data) : decodeURIComponent(data)
      } else {
        if (cache.has(href)) svgText = cache.get(href)
        else {
          const res = await fetch(href)
          if (!res.ok) continue
          svgText = await res.text()
          cache.set(href, svgText)
        }
      }
      const doc = new DOMParser().parseFromString(svgText, 'image/svg+xml')
      const srcSvg = doc.querySelector('svg')
      if (!srcSvg) continue
      const x = img.getAttribute('x') || '0'
      const y = img.getAttribute('y') || '0'
      const w = img.getAttribute('width') || '0'
      const h = img.getAttribute('height') || '0'
      const par = img.getAttribute('preserveAspectRatio') || 'xMidYMid meet'
      let vb = srcSvg.getAttribute('viewBox')
      if (!vb) {
        const sw = parseFloat(srcSvg.getAttribute('width'))
        const sh = parseFloat(srcSvg.getAttribute('height'))
        vb = (sw && sh) ? `0 0 ${sw} ${sh}` : '0 0 100 100'
      }
      const wrapper = document.createElementNS(NS, 'svg')
      wrapper.setAttribute('class', 'inlined-symbol')
      wrapper.setAttribute('x', x)
      wrapper.setAttribute('y', y)
      wrapper.setAttribute('width', w)
      wrapper.setAttribute('height', h)
      wrapper.setAttribute('viewBox', vb)
      wrapper.setAttribute('preserveAspectRatio', par)
      // 把源 SVG 内部所有节点(含其 <style>)搬进 wrapper,保持样式自包含
      while (srcSvg.firstChild) wrapper.appendChild(srcSvg.firstChild)
      img.replaceWith(wrapper)
    } catch (e) {
      // 内联失败(如符号文件缺失)则保留原 <image>,不阻断整体导出
    }
  }
}

/**
 * 所见即所得导出 PDF。
 * @param {SVGElement} svgEl        画布 SVG 元素(模板 ref svgRef)
 * @param {number} sheetWidthMm     图纸宽(mm,如 A3=420)
 * @param {number} sheetHeightMm    图纸高(mm)
 * @param {string} fileName         保存文件名
 * @param {number} dpi              光栅化精度,默认 300(打印级)
 * @param {number} lineWeight       线宽放大系数,默认 1.0;
 *   在 1.0 时严格按前端 stroke_px(数值=mm)输出,但 PDF 查看器把 300dpi 重采样到
 *   屏幕时抗锯齿灰边会让线显得发虚。把线宽整体放大到 ~1.4× 可让灰边占比变小,
 *   视觉上更接近前端直接渲染的 1px 黑线。
 */
export async function exportSheetScreenshotPdf({
  svgEl, sheetWidthMm, sheetHeightMm, fileName, dpi = 300, lineWeight = 1.0
}) {
  if (!svgEl) throw new Error('画布未就绪')

  const pxPerMm = dpi / 25.4
  const pxW = Math.ceil(sheetWidthMm * pxPerMm)
  const pxH = Math.ceil(sheetHeightMm * pxPerMm)

  // 1) 克隆并清理
  const clone = svgEl.cloneNode(true)
  clone.querySelectorAll(UI_LAYER_SELECTOR).forEach(el => el.remove())
  // 先把单元格符号 <image>(外部 URL)内联成真实 <svg>,避免导出图里符号丢失
  await inlineSymbolImages(clone)
  // 卡片阴影等展示样式不要;换成导出用的 root CSS 变量(线宽已放大)
  clone.removeAttribute('style')
  const rootVars = collectRootCssVars(lineWeight)
  if (rootVars) clone.setAttribute('style', rootVars)

  // 2) 视图内元素线宽补偿(必须在移除 vector-effect 前读原始元素的计算样式)
  compensateStrokeWidths(svgEl, clone, lineWeight)
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