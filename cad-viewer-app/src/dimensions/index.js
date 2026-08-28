// 标注引擎：交互状态机（工具切换 / 边线选择 / 预览 / 拖拽）
// 从 App.vue 抽离。依赖注入共享 state 与 helper，配合 core 完成标注放置与渲染。
//
// 注入 deps：
//   state（ref）: activeTool, dimHoveredEdge, dimFirstEdge, dimPending, dimPreview,
//                dimensions, selectedDimId, dimDragging, placedViews
//   helpers:
//     getEdgeByRef(viewId, idx, type)   → seg
//     makeEdgeRef(view, idx, type, seg) → edgeRef
//     resolveDimRef(ref)                → edgeRef
//     getSvgMousePoint(event)           → 图纸坐标
//     selectDim(id)
//     selectView(id)
//   core: createDimensionCore 返回的实例

import { ElMessage } from 'element-plus'
import { toLineSeg, toCircle, isParallel } from './geometry.js'
import { createDimensionCore } from './core.js'
import { resolveLinearMode, buildPendingPreview, commitPending } from './pending.js'

export function createDimEngine(deps) {
  const {
    activeTool,
    dimHoveredEdge,
    dimFirstEdge,
    dimPending,
    dimPreview,
    dimensions,
    selectedDimId,
    dimDragging,
    placedViews,
    getEdgeByRef,
    makeEdgeRef,
    resolveDimRef,
    getSvgMousePoint,
    selectDim,
    selectView,
    getSheetPoint,
    core
  } = deps

  const clearSelection = () => {
    dimFirstEdge.value = null
    dimPending.value = null
    dimHoveredEdge.value = null
    dimPreview.value = null
  }

  /** 工具切换 */
  function toggleTool(tool) {
    if (activeTool.value === tool) {
      activeTool.value = null
      clearSelection()
    } else {
      activeTool.value = tool
      clearSelection()
      selectedDimId.value = null
    }
  }

  /** 标注点击后的统一清理 */
  function finishDimPlacement(resetTool) {
    dimFirstEdge.value = null
    dimPending.value = null
    dimHoveredEdge.value = null
    dimPreview.value = null
    if (resetTool) activeTool.value = null
  }

  /** 待固定态落位：按当前预览偏移写入标注 */
  function commitPendingLinear() {
    const pending = dimPending.value
    if (!pending) return
    const id = commitPending(core, pending, dimPreview.value?.offset)
    if (!id) return
    selectDim(id)
    finishDimPlacement(pending.mode === 'single')
  }

  /** 边线选择处理 */
  function onDimEdgeSelect(hitEl, event) {
    const viewId = hitEl.dataset.dimView
    const idx = parseInt(hitEl.dataset.dimIdx, 10)
    const type = hitEl.dataset.dimType
    const seg = getEdgeByRef(viewId, idx, type)
    if (!seg) return
    const view = placedViews.value.find(v => v.id === viewId)
    if (!view) return
    const edgeRef = makeEdgeRef(view, idx, type, seg)
    if (!edgeRef) return

    if (activeTool.value === 'diameter') {
      // 直径：点击即放置（圆/圆弧/孔，circle 或可拟合的 polyline）
      if (toCircle(seg)) {
        const id = core.placeDiameterDim(edgeRef, dimPreview.value?.leaderAngle)
        if (id) selectDim(id)
      }
      return
    }

    if (activeTool.value === 'linear') {
      // 已选齐被测对象：本次点击在光标处落位
      if (dimPending.value) {
        commitPendingLinear()
        return
      }
      if (!dimFirstEdge.value) {
        dimFirstEdge.value = edgeRef
        return
      }
      const first = dimFirstEdge.value
      const same = first.viewId === viewId && first.idx === idx && first.type === type
      const pending = resolveLinearMode(first, same ? null : edgeRef)
      if (!pending) {
        ElMessage.warning(toCircle(first.seg) ? '请选择另一个孔或边线' : '线性标注需要选择平行边线')
        return
      }
      // 进入待固定态：之后预览跟着鼠标走，下一次点击才落位
      dimPending.value = pending
      dimPreview.value = buildPendingPreview(core, pending, getSvgMousePoint(event))
      return
    }

    if (activeTool.value === 'angle') {
      // 角度：点击边线1 → 点击边线2（不平行）
      if (!dimFirstEdge.value) {
        dimFirstEdge.value = edgeRef
        return
      }
      const first = dimFirstEdge.value
      if (first.viewId === viewId && first.idx === idx && first.type === type) {
        return // 同一根边线，忽略
      }
      if (isParallel(first.seg, seg)) {
        ElMessage.warning('角度标注需要选择不平行边线')
        return
      }
      // 放置角度
      const id = core.placeAngleDim(first, edgeRef, dimPreview.value?.radius)
      if (id) selectDim(id)
      finishDimPlacement()
    }
  }

  /** 预览更新（跟随鼠标） */
  function updateDimPreviewAt(event) {
    if (!activeTool.value) return
    const mousePos = getSvgMousePoint(event)
    if (!mousePos) return

    const P = core.previewBuilders

    if (activeTool.value === 'linear') {
      // 待固定态：模式已定，只让偏移跟随鼠标
      if (dimPending.value) {
        dimPreview.value = buildPendingPreview(core, dimPending.value, mousePos)
        return
      }
      // 如果有第一边线，边线类型需要按鼠标位置预览
      if (dimFirstEdge.value) {
        const first = dimFirstEdge.value
        const hit = dimHoveredEdge.value
        const isDiff = hit && (hit.viewId !== first.viewId || hit.idx !== first.idx || hit.type !== first.type)
        // 第一边为圆
        if (toCircle(first.seg)) {
          if (isDiff && toCircle(hit.seg)) {
            dimPreview.value = P.linearCenter(first, hit, mousePos)
          } else if (isDiff && toLineSeg(hit.seg)) {
            dimPreview.value = P.linearCircleEdge(first, hit, mousePos)
          } else {
            dimPreview.value = P.centerMark(first)
          }
          return
        }
        // 第一边为线，hover 到圆 → 圆心到边线距离
        if (isDiff && toCircle(hit.seg) && toLineSeg(first.seg)) {
          dimPreview.value = P.linearCircleEdge(hit, first, mousePos)
          return
        }
        // 检测鼠标是否在另一条平行边线上
        if (isDiff) {
          const seg2 = getEdgeByRef(hit.viewId, hit.idx, hit.type)
          if (seg2 && isParallel(first.seg, seg2)) {
            dimPreview.value = P.linearParallel(first, hit, mousePos)
            return
          }
        }
        // 默认：单边对齐标注
        dimPreview.value = P.linearSingle(first, mousePos)
        return
      }
      // 无第一边线：跟随光标预览最近边线
      if (dimHoveredEdge.value) {
        const seg = dimHoveredEdge.value.seg
        if (toCircle(seg)) {
          // 圆：仅显示中心标记十字，等待选择第二孔
          dimPreview.value = P.centerMark(dimHoveredEdge.value)
        } else if (toLineSeg(seg)) {
          dimPreview.value = P.linearSingle(dimHoveredEdge.value, mousePos)
        }
      }
      return
    }

    if (activeTool.value === 'diameter') {
      // 直径预览：跟随光标（circle 或可拟合为圆的 polyline）
      if (dimHoveredEdge.value && toCircle(dimHoveredEdge.value.seg)) {
        dimPreview.value = P.diameter(dimHoveredEdge.value, mousePos)
      }
      return
    }

    if (activeTool.value === 'angle') {
      if (dimFirstEdge.value) {
        const first = dimFirstEdge.value
        if (dimHoveredEdge.value) {
          const seg2 = getEdgeByRef(dimHoveredEdge.value.viewId, dimHoveredEdge.value.idx, dimHoveredEdge.value.type)
          if (seg2 && !isParallel(first.seg, seg2)) {
            dimPreview.value = P.angle(first, dimHoveredEdge.value, mousePos)
            return
          }
        }
      }
      if (dimHoveredEdge.value && toLineSeg(dimHoveredEdge.value.seg)) {
        // 单选线预览：显示角度候选
        dimPreview.value = null
      }
    }
  }

  /** 标注 mousedown：开始拖拽 */
  function onDimMouseDown(event, dim) {
    if (activeTool.value) return
    const mousePos = getSvgMousePoint(event)
    if (!mousePos) return
    selectDim(dim.id)
    dimDragging.value = { id: dim.id, type: dim.type }
  }

  /** 全局 mouseup：结束标注拖拽 */
  function onGlobalDimMouseUp() {
    dimDragging.value = null
  }

  /** 选中标注 */
  function selectDimension(id) {
    selectDim(id)
  }

  /** 删除选中标注 */
  function deleteSelectedDim() {
    if (!selectedDimId.value) return
    dimensions.value = dimensions.value.filter(d => d.id !== selectedDimId.value)
    selectedDimId.value = null
  }

  /** 键盘事件：Delete 删除选中标注，Esc 放弃尚未落位的标注 */
  function onKeyDown(event) {
    if (event.key === 'Delete' || event.key === 'Del') {
      if (selectedDimId.value) deleteSelectedDim()
      return
    }
    if (event.key === 'Escape' && (dimFirstEdge.value || dimPending.value)) {
      clearSelection()
    }
  }

  /** 标注拖拽更新（由全局 mousemove 调用） */
  function onDimDragMove(event) {
    const drag = dimDragging.value
    if (!drag) return
    const dim = dimensions.value.find(item => item.id === drag?.id)
    const mousePos = getSvgMousePoint(event)
    if (!dim || !mousePos) return
    core.updateDimDrag(dim, mousePos)
  }

  return {
    toggleTool,
    onDimEdgeSelect,
    updateDimPreviewAt,
    commitPendingLinear,
    onDimMouseDown,
    onDimDragMove,
    onGlobalDimMouseUp,
    deleteSelectedDim,
    onKeyDown,
    clearSelection,
    // 供模板/删除视图时清理标注
    clearDimState: clearSelection
  }
}

export { createDimensionCore } from './core.js'
export { createDimensionCore as coreFactory } from './core.js'
export * from './geometry.js'
