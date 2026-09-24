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
    angleSubMode,
    centerSubMode,
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
    core,
    record,
    undo
  } = deps

  // 直径/中心标记是"点击即落位",落位后预览要压住,直到鼠标移开落位点;
  // 否则 mousemove 会立刻在原位重建一份预览,与刚落位的标注叠成"两个标注"
  const PREVIEW_REARM_DIST = 8
  let previewSuppressAt = null
  // 一次拖拽(移动标注/文字/延长线手柄)只记录一次快照,整体作为一个撤销步
  let dragSnapshotTaken = false

  const clearSelection = () => {
    dimFirstEdge.value = null
    dimPending.value = null
    dimHoveredEdge.value = null
    dimPreview.value = null
    previewSuppressAt = null
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
    previewSuppressAt = null
    if (resetTool) activeTool.value = null
  }

  /** 落位瞬间清预览并记下鼠标位置,等鼠标移开 8px 再允许预览重新出现 */
  function suppressPreviewAfterPlace(mousePos) {
    dimPreview.value = null
    previewSuppressAt = mousePos || null
  }

  // ===== 中心夹角:选 顶点 → 点1 → 点2,再移动鼠标定半径、点击落位 =====

  /** 命中对象 → 点引用:圆取圆心;直线取离鼠标更近的端点 */
  function pickPointRef(edgeRef, mousePos) {
    let pointKind = 'center'
    const line = toLineSeg(edgeRef.seg)
    if (line && mousePos) {
      const a = getSheetPoint(edgeRef.view, line.x1, line.y1)
      const b = getSheetPoint(edgeRef.view, line.x2, line.y2)
      const da = Math.hypot(mousePos.x - a.x, mousePos.y - a.y)
      const db = Math.hypot(mousePos.x - b.x, mousePos.y - b.y)
      pointKind = db < da ? 'end' : 'start'
    }
    return {
      viewId: edgeRef.viewId, idx: edgeRef.idx, type: edgeRef.type, pointKind
    }
  }

  function isSameDimPoint(refA, refB) {
    return !!refA && !!refB
      && refA.viewId === refB.viewId && refA.idx === refB.idx
      && refA.type === refB.type && (refA.pointKind || 'center') === (refB.pointKind || 'center')
  }

  function onAnglePointSelect(edgeRef, event) {
    const mousePos = getSvgMousePoint(event)
    const pointRef = pickPointRef(edgeRef, mousePos)
    const pending = dimPending.value
    if (!pending || pending.mode !== 'angle-points') {
      // 第一个点作顶点(通常是法兰中心)
      dimPending.value = { mode: 'angle-points', vertexRef: pointRef, points: [] }
      dimPreview.value = null
      return
    }
    if (pending.points.length === 0) {
      if (isSameDimPoint(pending.vertexRef, pointRef)) return
      pending.points = [pointRef]
      dimPreview.value = null
      return
    }
    // 第二个被测点:选齐,进入"鼠标定半径"的预览态
    pending.points = [pending.points[0], pointRef]
    dimPreview.value = core.previewBuilders.anglePoints(
      pending.vertexRef, pending.points[0], pending.points[1], mousePos)
  }

  /** 落位中心夹角;选齐前或几何不成立时返回 false */
  function commitAnglePoints() {
    const pending = dimPending.value
    if (!pending || pending.mode !== 'angle-points' || pending.points.length < 2) return false
    const radius = dimPreview.value?.radius ?? 200
    const id = core.placeAnglePointsDim(
      pending.vertexRef, pending.points[0], pending.points[1], radius)
    if (!id) return false
    selectDim(id)
    finishDimPlacement(false)
    return true
  }

  // ===== 孔组中心标记:逐个点孔(再点一次取消),回车/点空白落位 =====

  /**
   * 就近找孔:找圆周经过鼠标附近的最小圆。
   * 图纸边线极密(单视图 700+ 条命中带互相重叠),而孔的边线往往是 polyline,
   * 靠 elementFromPoint 命中基本选不准孔;这里直接按几何判断,点在圆周附近即可。
   */
  function pickCircleNear(mousePos) {
    if (!mousePos) return null
    let best = null
    for (const view of placedViews.value) {
      const scale = view.scale || 1
      const tolerance = Math.max(6, 12 / scale)   // ≈屏幕 12px
      const lists = [
        { segs: view.edges, type: 'edges' },
        { segs: view.hiddenEdges, type: 'hiddenEdges' }
      ]
      for (const list of lists) {
        const segs = list.segs || []
        for (let i = 0; i < segs.length; i++) {
          const circ = toCircle(segs[i])
          if (!circ) continue
          const r = circ.r * scale
          if (r < 3) continue                     // 噪声小圆跳过
          const c = getSheetPoint(view, circ.cx, circ.cy)
          const d = Math.abs(Math.hypot(mousePos.x - c.x, mousePos.y - c.y) - r)
          if (d > tolerance) continue
          if (!best || d < best.d) best = { view, idx: i, type: list.type, seg: segs[i], d }
        }
      }
    }
    return best ? { ...makeEdgeRef(best.view, best.idx, best.type, best.seg), d: best.d } : null
  }

  /**
   * 几何命中已放置孔组的分度圆(虚线圆),与 pickCircleNear 同一算法骨架。
   * 分度圆的 DOM 命中带(.dim-bolt-hit)在标注工具下让路给孔/边线,虚线本身
   * 只有 1px 极难点中;这里按"点到圆周距离 ≤ tolerance"几何判定。
   * 返回 { dim, ref, circle, d }:ref 为分度圆的合成 edgeRef(局部坐标 seg + view,
   * 可直接喂直径/中心标记的几何构建),circle 为图纸坐标 {x,y,r};未命中返回 null。
   */
  function pickBoltCircleNear(mousePos) {
    if (!mousePos) return null
    let best = null
    for (const dim of dimensions.value) {
      if (dim.type !== 'center-mark' || !(dim.group || dim.groupCenter)) continue
      const ref = core.buildBoltCircleRef(dim.refs)
      if (!ref || !ref.view) continue
      const scale = ref.view.scale || 1
      const tolerance = Math.max(6, 12 / scale)   // ≈屏幕 12px,与 pickCircleNear 一致
      const c = getSheetPoint(ref.view, ref.seg.cx, ref.seg.cy)
      const r = ref.seg.r * scale
      const d = Math.abs(Math.hypot(mousePos.x - c.x, mousePos.y - c.y) - r)
      if (d > tolerance) continue
      if (!best || d < best.d) best = { dim, ref, circle: { x: c.x, y: c.y, r }, d }
    }
    return best
  }

  /** 加入/移出一个孔;满 3 个孔起出预览(分度圆 + 各孔径向十字) */
  function onCenterMarkGroupPick(edgeRef) {
    const ref = { viewId: edgeRef.viewId, idx: edgeRef.idx, type: edgeRef.type }
    let pending = dimPending.value
    if (!pending || pending.mode !== 'bolt-circle') {
      pending = { mode: 'bolt-circle', circles: [] }
      dimPending.value = pending
    }
    const key = `${ref.viewId}#${ref.idx}#${ref.type}`
    const at = pending.circles.findIndex(c => `${c.viewId}#${c.idx}#${c.type}` === key)
    if (at >= 0) pending.circles.splice(at, 1)
    else pending.circles.push(ref)
    // 孔数不足时 build 返回 null,预览自然清空
    dimPreview.value = core.buildCenterMarkGroupGeometry(pending.circles.map(resolveDimRef))
  }

  /** 落位孔组中心标记;选孔不足或几何不成立时返回 false */
  function commitCenterMarkGroup() {
    const pending = dimPending.value
    if (!pending || pending.mode !== 'bolt-circle') return false
    const id = core.placeCenterMarkGroupDim(pending.circles)
    if (!id) return false
    selectDim(id)
    finishDimPlacement(false)
    return true
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

    // 中心夹角已选齐三点:这次点击只用来按鼠标位置定半径并落位
    if (dimPending.value?.mode === 'angle-points' && dimPending.value.points.length >= 2) {
      commitAnglePoints()
      return
    }

    if (activeTool.value === 'center-mark') {
      if (centerSubMode.value === 'group') {
        // 命中对象认不出圆时,按鼠标位置就近找孔(密集边线里命不中孔)
        const circleRef = toCircle(seg) ? edgeRef : pickCircleNear(getSvgMousePoint(event))
        if (circleRef) onCenterMarkGroupPick(circleRef)
        return
      }
      if (toCircle(seg)) {
        // 孔位中心标记：点击即放置，十字线长度自动取该孔直径
        const id = core.placeCenterMarkDim(edgeRef)
        if (id) {
          selectDim(id)
          suppressPreviewAfterPlace(getSvgMousePoint(event))
        }
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
        if (id) {
          selectDim(id)
          suppressPreviewAfterPlace(getSvgMousePoint(event))
        }
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
      if (angleSubMode.value === 'center') {
        // 中心夹角：顶点 → 被测点1 → 被测点2 → 点一次定半径落位
        onAnglePointSelect(edgeRef, event)
        return
      }
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

    // 刚落位的标注:鼠标未挪开之前不再画预览,避免预览与标注自身重叠
    if (previewSuppressAt) {
      const moved = Math.hypot(mousePos.x - previewSuppressAt.x, mousePos.y - previewSuppressAt.y)
      if (moved < PREVIEW_REARM_DIST) {
        dimPreview.value = null
        return
      }
      previewSuppressAt = null
    }

    // 直径/中心标记:已放置孔组的分度圆几何命中(择近于孔)优先出预览。
    // 分度圆 DOM 命中带在工具下让路给孔、虚线仅 1px 极难点中;鼠标贴着分度圆时
    // 按"分度圆"出预览——直径:贯穿线/引线跟随鼠标,中心标记:孔组中心的十字,
    // 与 mousedown 的放置行为完全一致(同一择近判定)。
    // 孔组选孔中(dimPending)不干扰:保留已选孔的分度圆+径向十字预览
    if ((activeTool.value === 'diameter' || activeTool.value === 'center-mark') && !dimPending.value) {
      const bolt = pickBoltCircleNear(mousePos)
      if (bolt) {
        const hole = pickCircleNear(mousePos)
        if (!hole || bolt.d <= hole.d) {
          // 清边线高亮:预览按分度圆,高亮孔会造成"预览/高亮"分裂
          if (dimHoveredEdge.value) dimHoveredEdge.value = null
          if (activeTool.value === 'diameter') {
            dimPreview.value = diameterSubMode.value === 'leader'
              ? core.buildDiameterLeaderPreview(bolt.ref, mousePos)
              : core.previewBuilders.diameter(bolt.ref, mousePos)
          } else {
            dimPreview.value = core.buildCenterMarkGroupGeometry(
              (bolt.dim.refs || []).map(resolveDimRef), true)
          }
          return
        }
      }
    }

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
      // 孔组预览由选孔驱动(不用跟鼠标),鼠标移动不重建
      if (centerSubMode.value === 'group') return
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
      if (angleSubMode.value === 'center') {
        // 选齐三点后预览跟鼠标走(半径=鼠标到顶点的距离),选齐前不出预览
        const pending = dimPending.value
        if (pending?.mode === 'angle-points' && pending.points.length >= 2) {
          dimPreview.value = P.anglePoints(
            pending.vertexRef, pending.points[0], pending.points[1], mousePos)
        } else {
          dimPreview.value = null
        }
        return
      }
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
    // 中心标记工具下点孔组的虚线分度圆:把它当成"一个孔",在分度圆圆心打十字
    if (activeTool.value === 'center-mark' && dim.type === 'center-mark'
        && (dim.group || dim.groupCenter)) {
      const id = core.placeCenterMarkAtGroupCenter(dim.refs)
      if (id) {
        selectDim(id)
        suppressPreviewAfterPlace(getSvgMousePoint(event))
      }
      return
    }
    // 直径工具下点孔组的虚线分度圆:对分度圆做直径标注(显示其 PCD)。
    // 分度圆不是真实边线,命中带 .dim-bolt-hit 挂在孔组标注上,由这里转成
    // 直径标注(引用孔组各孔,换型号后分度圆变化、直径随之跟随)。
    // 子模式与预览参数跟 hover 预览一致:引线模式用预览的 textLeft,
    // 直线模式用预览角度,所见即所得
    if (activeTool.value === 'diameter' && dim.type === 'center-mark'
        && dim.group && (dim.refs || []).length >= 3) {
      const pt = getSvgMousePoint(event)
      const pv = dimPreview.value
      const id = core.placeDiameterOnBoltCircleDim(dim.refs,
        diameterSubMode.value === 'leader'
          ? {
              mode: 'leader',
              textLeft: pv?.textLeft || (pt ? { x: pt.x - 60, y: pt.y } : null),
              leaderAngle: pv?.leaderAngle
            }
          : { leaderAngle: pv?.leaderAngle })
      if (id) {
        selectDim(id)
        suppressPreviewAfterPlace(pt)
      }
      return
    }
    const mousePos = getSvgMousePoint(event)
    if (!mousePos) return
    selectDim(dim.id)
    dragSnapshotTaken = false
    const drag = { id: dim.id, type: dim.type, startMouse: mousePos, startOffset: dim.offset }
    // 直径标注补抓取快照:拖拽按"相对增量"跟手(否则引线退化为绝对语义跳 60px,
    // 贯穿直线在抓点近圆心时角度噪声乱跳)。引线快照取限位后的文字位置——
    // 旧数据可能存的是限位外的远点,而显示已收紧,快照必须与显示一致
    if (dim.type === 'diameter') {
      if (dim.diameterMode === 'leader') {
        drag.startTextLeft = core.diameterTextLeftSheetClamped(dim)
      } else {
        drag.startLeaderAngle = dim.leaderAngle ?? -Math.PI / 4
        drag.startLeaderLength = dim.leaderLength ?? 30
      }
    }
    dimDragging.value = drag
  }

  /** 文字标签 mousedown:开始拖动文字(只改 textSlide,不动尺寸线)
   *  startMouse/startSlide 供直径标注"抓住文字跟随鼠标"用(按位移增量沿直径线滑动);
   *  线性标注仍按鼠标绝对投影定位,不看这两个字段。 */
  function onDimTextMouseDown(event, dim) {
    const mousePos = getSvgMousePoint(event)
    if (!mousePos) return
    selectDim(dim.id)
    dragSnapshotTaken = false
    const drag = {
      id: dim.id,
      type: dim.type,
      part: 'text',
      startMouse: mousePos,
      startSlide: dim.textSlide || 0
    }
    dimDragging.value = drag
  }

  /** 延长线手柄 mousedown:开始拖拽调整 lineExtension(尺寸线两端外延长度) */
  function onDimExtensionHandleDown(event, dim, endSide) {
    const mousePos = getSvgMousePoint(event)
    if (!mousePos) return
    selectDim(dim.id)
    dragSnapshotTaken = false
    dimDragging.value = { id: dim.id, type: dim.type, part: 'extension', endSide }
  }

  /** 全局 mouseup：结束标注拖拽 */
  function onGlobalDimMouseUp() {
    dimDragging.value = null
    dragSnapshotTaken = false
  }

  /** 选中标注 */
  function selectDimension(id) {
    selectDim(id)
  }

  /** 删除选中标注 */
  function deleteSelectedDim() {
    if (!selectedDimId.value) return
    record && record()
    dimensions.value = dimensions.value.filter(d => d.id !== selectedDimId.value)
    selectedDimId.value = null
  }

  /** 键盘事件：Ctrl+Z 撤销 / Delete 删除选中标注 / Esc 放弃尚未落位的标注 */
  function onKeyDown(event) {
    // 编辑属性输入框时,交给原生文本撤销,不触发标注撤销/删除
    const ae = document.activeElement
    const typing = ae && (ae.tagName === 'INPUT' || ae.tagName === 'TEXTAREA' || ae.isContentEditable)
    if ((event.ctrlKey || event.metaKey) && (event.key === 'z' || event.key === 'Z')) {
      if (typing) return
      event.preventDefault()
      undo && undo()
      return
    }
    if (event.key === 'Delete' || event.key === 'Del') {
      if (typing) return
      if (selectedDimId.value) deleteSelectedDim()
      return
    }
    // 孔组中心标记:回车落位(点空白同样可落位)
    if (event.key === 'Enter' && commitCenterMarkGroup()) return
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
    // 一次拖拽只在首次移动时记录(拖拽前状态),之后连续移动不再重复记录
    if (!dragSnapshotTaken) {
      record && record()
      dragSnapshotTaken = true
    }
    if (drag.part === 'text') {
      core.updateDimTextDrag(dim, mousePos, drag)
    } else if (drag.part === 'extension') {
      core.updateDimExtensionDrag(dim, mousePos, drag.endSide)
    } else {
      // 必须把 drag 快照传下去:直径(尤其引线模式)按抓取时刻的增量跟手,
      // 不传则退回绝对跟随,引线抓点偏移丢失、近圆心处角度噪声乱跳
      core.updateDimDrag(dim, mousePos, drag)
    }
  }

  return {
    toggleTool,
    onDimEdgeSelect,
    onMotorEnvelopePick,
    updateDimPreviewAt,
    commitPendingLinear,
    commitAnglePoints,
    onDimMouseDown,
    onDimTextMouseDown,
    onDimExtensionHandleDown,
    onDimDragMove,
    onGlobalDimMouseUp,
    deleteSelectedDim,
    onKeyDown,
    commitCenterMarkGroup,
    onCenterMarkGroupPick,
    pickCircleNear,
    pickBoltCircleNear,
    suppressPreviewAfterPlace,
    clearSelection,
    // 供模板/删除视图时清理标注
    clearDimState: clearSelection
  }
}

export { createDimensionCore } from './core.js'
export { createDimensionCore as coreFactory } from './core.js'
export * from './geometry.js'
