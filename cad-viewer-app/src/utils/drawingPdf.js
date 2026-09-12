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

/** 把 :root 上的 CSS 变量收集成 style 字符串。
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

/** 节点自身及祖先的累计缩放:transform 的 scale + 嵌套 svg 的 viewBox 映射 */
function cumulativeScale(el, root) {
  let s = 1
  for (let n = el; n && n !== root; n = n.parentElement) {
    if (!n.getAttribute) continue
    const m = (n.getAttribute('transform') || '').match(/scale\(\s*([-\d.]+)/)
    if (m) s *= parseFloat(m[1])
    if (n.tagName === 'svg' && n.hasAttribute('viewBox')) {
      const vb = n.getAttribute('viewBox').split(/[\s,]+/).map(parseFloat)
      const w = parseFloat(n.getAttribute('width'))
      if (vb.length === 4 && vb[2] > 0 && w > 0) s *= w / vb[2]
    }
  }
  return s
}

/** 把"屏幕恒定线宽"固化为图纸 mm。
 *  non-scaling-stroke 元素在前端任何缩放下都显示 stroke_px 个屏幕像素,
 *  但克隆图光栅化成 <img> 后该特性失效,线宽会按用户单位(mm)解释。
 *  导出前按当前画布缩放换算: mm = 屏幕px / sheetZoom / 累计scale,
 *  内联写回并关掉 vector-effect,PDF 与屏幕所见一致。
 *  需要把克隆临时挂进 document 才能读计算样式。 */
function freezeStrokes(clone, sheetZoom) {
  clone.style.position = 'fixed'
  clone.style.left = '-100000px'
  clone.style.top = '0'
  document.body.appendChild(clone)
  try {
    for (const el of clone.querySelectorAll('*')) {
      const cs = getComputedStyle(el)
      if (cs.getPropertyValue('vector-effect') !== 'non-scaling-stroke') continue
      if (cs.stroke === 'none') continue
      const px = parseFloat(cs.strokeWidth)
      if (!Number.isFinite(px) || px <= 0) continue
      const mm = px / sheetZoom / cumulativeScale(el, clone)
      el.style.setProperty('stroke-width', mm.toFixed(5))
      el.style.setProperty('vector-effect', 'none')
      el.removeAttribute('vector-effect')
    }
  } finally {
    clone.remove()
    // 只清掉本函数加的定位样式,保留调用前写入的 root CSS 变量
    clone.style.removeProperty('position')
    clone.style.removeProperty('left')
    clone.style.removeProperty('top')
  }
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
 * @param {number} sheetZoom        导出瞬间画布缩放(屏幕px/mm),
 *   屏幕恒定线宽按它折成图纸 mm,保证 PDF 与当前屏幕所见一致
 */
export async function exportSheetScreenshotPdf({
  svgEl, sheetWidthMm, sheetHeightMm, fileName, dpi = 300, sheetZoom = 1
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
  // 卡片阴影等展示样式不要;换成导出用的 root CSS 变量
  clone.removeAttribute('style')
  const rootVars = collectRootCssVars()
  if (rootVars) clone.setAttribute('style', rootVars)

  // 2) 屏幕恒定线宽固化为图纸 mm(需临时挂载读计算样式)
  freezeStrokes(clone, sheetZoom)

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