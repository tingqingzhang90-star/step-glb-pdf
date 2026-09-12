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
    diameterSubMode,
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
    getSheetPoint,
    getMotorEnvelope,
    selectDim,
    selectView,
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

    if (activeTool.value === 'center-mark') {
      // 孔位中心标记：点击即放置，十字线长度自动取该孔直径
      if (toCircle(seg)) {
        const id = core.placeCenterMarkDim(edgeRef)
        if (id) selectDim(id)
      }
      return
    }

    if (activeTool.value === 'diameter') {
      // 直径：点击即放置（圆/圆弧/孔，circle 或可拟合的 polyline）
      if (toCircle(seg)) {
        let id
        if (diameterSubMode.value === 'leader') {
          const mousePos = getSvgMousePoint(event)
          const preview = dimPreview.value
          id = core.placeDiameterLeaderDim(
            edgeRef,
            preview?.textLeft || (mousePos ? { x: mousePos.x - 60, y: mousePos.y } : { x: 0, y: 0 }),
            preview?.leaderAngle || -Math.PI / 4
          )
        } else {
          id = core.placeDiameterDim(edgeRef, dimPreview.value?.leaderAngle)
        }
        if (id) selectDim(id)
      }
      return
    }

    if (activeTool.value === 'motor-envelope') {
      // 电机包络：绑定当前视图的电机包络端面，换型号自动跟随
      const envelope = getMotorEnvelope ? getMotorEnvelope(view) : null
      if (!envelope) {
        ElMessage.warning('该视图下无法标注电机包络尺寸')
        return
      }
      const mousePos = getSvgMousePoint(event)
      const offset = mousePos
        ? core.getMotorEnvelopeOffsetFromMouse(view, envelope, getSheetPoint, mousePos)
        : 50
      const id = core.placeMotorEnvelopeDim(view, envelope, edgeRef, offset, '电机减速机尺寸')
      if (id) selectDim(id)
      finishDimPlacement(true)
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

  /** 电机包络落位：由视图透明命中层点击触发。
   *  电机包络来自后端 motor_envelope、与具体边线无关,只需知道落在哪个视图上,
   *  因此不走 onDimEdgeSelect(那要求命中某条边线)。 */
  function onMotorEnvelopePick(event, view) {
    if (activeTool.value !== 'motor-envelope' || !view) return
    const envelope = getMotorEnvelope ? getMotorEnvelope(view) : null
    if (!envelope) {
      ElMessage.warning('该视图下无法标注电机包络尺寸')
      return
    }
    const mousePos = getSvgMousePoint(event)
    const offset = mousePos
      ? core.getMotorEnvelopeOffsetFromMouse(view, envelope, getSheetPoint, mousePos)
      : 50
    // refs 只记录所属视图：idx/type 对电机包络无意义,重绑走 bind_motor 分支
    const id = core.placeMotorEnvelopeDim(
      view, envelope, { viewId: view.id, idx: -1, type: 'edges' }, offset, '电机减速机尺寸')
    if (id) selectDim(id)
    dimHoveredEdge.value = null
    finishDimPlacement(true)
  }

  /** 预览更新（跟随鼠标） */
  function updateDimPreviewAt(event) {
    if (!activeTool.value) return
    const mousePos = getSvgMousePoint(event)
    if (!mousePos) return

    const P = core.previewBuilders

    if (activeTool.value === 'motor-envelope') {
      if (dimHoveredEdge.value) {
        const view = dimHoveredEdge.value.view
        const envelope = getMotorEnvelope ? getMotorEnvelope(view) : null
        if (envelope) {
          const offset = core.getMotorEnvelopeOffsetFromMouse(
            view, envelope, getSheetPoint, mousePos)
          dimPreview.value = core.buildMotorEnvelopeGeometry(
            view, envelope, getSheetPoint, offset)
        }
      }
      return
    }

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
            // 未选第二对象或重复选第一对象:贴合圆周的中心十字提示
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
          // 圆：贴合圆周的中心十字,等待选择第二孔
          dimPreview.value = P.centerMark(dimHoveredEdge.value)
        } else if (toLineSeg(seg)) {
          dimPreview.value = P.linearSingle(dimHoveredEdge.value, mousePos)
        }
      }
      return
    }

    if (activeTool.value === 'center-mark') {
      // 孔位中心标记预览：十字线随该孔直径变化
      if (dimHoveredEdge.value && toCircle(dimHoveredEdge.value.seg)) {
        dimPreview.value = P.centerMark(dimHoveredEdge.value)
      }
      return
    }

    if (activeTool.value === 'diameter') {
      // 直径预览：跟随光标（circle 或可拟合为圆的 polyline）
      if (dimHoveredEdge.value && toCircle(dimHoveredEdge.value.seg)) {
        if (diameterSubMode.value === 'leader') {
          dimPreview.value = core.buildDiameterLeaderPreview(dimHoveredEdge.value, mousePos)
        } else {
          dimPreview.value = P.diameter(dimHoveredEdge.value, mousePos)
        }
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

  /** 标注 mousedown：开始拖拽(无论标注工具是否激活)
   * 之前在 activeTool 激活时直接 return,导致已放置标注在标注模式下无法调整位置。
   * 现状:`@mousedown.stop` 阻止冒泡,不会触发 SVG 根的"落位"逻辑,所以这里打开拖拽
   * 不会与标注流程冲突;center-mark 无可调参数,自然不会被 updateDimDrag 影响。 */
  function onDimMouseDown(event, dim) {
    const mousePos = getSvgMousePoint(event)
    if (!mousePos) return
    selectDim(dim.id)
    dimDragging.value = { id: dim.id, type: dim.type, startMouse: mousePos, startOffset: dim.offset }
  }

  /** 文字标签 mousedown:开始拖动文字(只改 textSlide,不动尺寸线) */
  function onDimTextMouseDown(event, dim) {
    const mousePos = getSvgMousePoint(event)
    if (!mousePos) return
    selectDim(dim.id)
    dimDragging.value = { id: dim.id, type: dim.type, part: 'text' }
  }

  /** 延长线手柄 mousedown:开始拖拽调整 lineExtension(尺寸线两端外延长度) */
  function onDimExtensionHandleDown(event, dim, endSide) {
    const mousePos = getSvgMousePoint(event)
    if (!mousePos) return
    selectDim(dim.id)
    dimDragging.value = { id: dim.id, type: dim.type, part: 'extension', endSide }
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
    if (drag.part === 'text') {
      core.updateDimTextDrag(dim, mousePos)
    } else if (drag.part === 'extension') {
      core.updateDimExtensionDrag(dim, mousePos, drag.endSide)
    } else {
      core.updateDimDrag(dim, mousePos)
    }
  }

  return {
    toggleTool,
    onDimEdgeSelect,
    onMotorEnvelopePick,
    updateDimPreviewAt,
    commitPendingLinear,
    onDimMouseDown,
    onDimTextMouseDown,
    onDimExtensionHandleDown,
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
