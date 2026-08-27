// 视图几何与对齐纯函数（无 Vue 依赖，从 App.vue 抽离）
// 仅处理视图包围盒、初始比例、放置定位、中心点与投影对齐检测。

const ALIGN_SNAP_THRESHOLD = 8 // 吸附阈值（SVG 坐标 px）

// 垂直对齐组：水平轴平行于 X 轴 → 拖拽时 X 中心对齐
export const VERTICAL_ALIGN_GROUP_X = new Set(['front', 'back', 'top', 'bottom'])
// 垂直对齐组：水平轴平行于 Z 轴 → 拖拽时 X 中心对齐（缸体长轴方向）
export const VERTICAL_ALIGN_GROUP_Z = new Set(['left', 'right', 'left_top'])
// 水平对齐组：垂直轴平行于 Y 轴 → 拖拽时 Y 中心对齐
export const HORIZONTAL_ALIGN_GROUP_Y = new Set(['front', 'back', 'left', 'right'])

export function normalizeViewBBox(view) {
  return view.bbox || { x: 0, y: 0, width: 400, height: 300 }
}

/** 计算视图所有可见/隐藏边的内容包围盒（SVG 视图局部坐标） */
export function computeContentBBox(view) {
  const points = []
  const collectPoint = (x, y) => {
    if (Number.isFinite(x) && Number.isFinite(y)) {
      points.push([x, y])
    }
  }

  for (const seg of [...(view.edges || []), ...(view.hidden_edges || [])]) {
    if (!seg || !seg.type) continue
    if (seg.type === 'line') {
      collectPoint(seg.x1, seg.y1)
      collectPoint(seg.x2, seg.y2)
    } else if (seg.type === 'circle') {
      collectPoint(seg.cx - seg.r, seg.cy - seg.r)
      collectPoint(seg.cx + seg.r, seg.cy + seg.r)
    } else if (seg.type === 'polyline') {
      for (const p of seg.points || []) {
        collectPoint(p[0], p[1])
      }
    }
  }

  if (points.length === 0) {
    return normalizeViewBBox(view)
  }

  const xs = points.map(p => p[0])
  const ys = points.map(p => p[1])
  const minX = Math.min(...xs)
  const minY = Math.min(...ys)
  const maxX = Math.max(...xs)
  const maxY = Math.max(...ys)
  return {
    x: minX,
    y: minY,
    width: Math.max(1, maxX - minX),
    height: Math.max(1, maxY - minY)
  }
}

/** 首次放置的视图初始比例：长边对齐 260px */
export function getInitialViewScale(view) {
  const bbox = computeContentBBox(view)
  const targetLongEdge = 260
  const longEdge = Math.max(bbox.width || 1, bbox.height || 1)
  return Math.max(0.35, Math.min(2.4, targetLongEdge / longEdge))
}

/** 以鼠标落点为视图中心，返回放置位置 */
export function getCenteredViewPlacement(view, point, scale) {
  const bbox = computeContentBBox(view)
  return {
    x: point.x - (bbox.x + bbox.width / 2) * scale,
    y: point.y - (bbox.y + bbox.height / 2) * scale,
    scale,
    bbox
  }
}

/** 视图中心在图纸中的坐标（含显示比例） */
export function getViewCenterInSheet(pv, displayScale) {
  return {
    x: pv.x + (pv.contentBBox.x + pv.contentBBox.width / 2) * displayScale,
    y: pv.y + (pv.contentBBox.y + pv.contentBBox.height / 2) * displayScale
  }
}

/**
 * 投影对齐检测：遍历已放置视图，返回吸附偏移与对齐引导线。
 * @param {number} centerX 当前拖拽视图中心
 * @param {number} centerY
 * @param {string} skipId  忽略的视图 id
 * @param {Array}  placedViews 已放置视图数组（元素需含 name/contentBBox/x/y）
 * @param {(pv)=>number} getScale 取视图显示比例
 */
export function detectAlignment(centerX, centerY, skipId, placedViews, getScale) {
  const guides = []
  let snapDx = 0, snapDy = 0
  let bestDistX = Infinity, bestDistY = Infinity

  for (const pv of placedViews) {
    if (pv.id === skipId) continue
    const otherCenter = getViewCenterInSheet(pv, getScale(pv))

    // 垂直对齐线（X 中心对齐）— 同属垂直对齐组的视图
    if (VERTICAL_ALIGN_GROUP_X.has(pv.name) || VERTICAL_ALIGN_GROUP_Z.has(pv.name)) {
      const dist = Math.abs(centerX - otherCenter.x)
      if (dist < ALIGN_SNAP_THRESHOLD && dist < bestDistX) {
        bestDistX = dist
        snapDx = otherCenter.x - centerX
        guides.push({ type: 'vertical', pos: otherCenter.x })
      }
    }

    // 水平对齐线（Y 中心对齐）— 同属水平对齐组的视图
    if (HORIZONTAL_ALIGN_GROUP_Y.has(pv.name)) {
      const dist = Math.abs(centerY - otherCenter.y)
      if (dist < ALIGN_SNAP_THRESHOLD && dist < bestDistY) {
        bestDistY = dist
        snapDy = otherCenter.y - centerY
        guides.push({ type: 'horizontal', pos: otherCenter.y })
      }
    }
  }

  return { guides, snapDx, snapDy }
}
