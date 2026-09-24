// 标注工具:状态声明 + 引擎装配(dimCore 几何构建 / dimEngine 交互状态机)
import { ref, computed } from 'vue'
import { createDimEngine, coreFactory } from '@/dimensions/index.js'
import { toCircle, toLineSeg } from '@/dimensions/geometry.js'

export function useDimensions({ placedViews, selectedViewId, coords, getMotorEnvelope }) {
  const activeTool = ref(null)       // null | 'linear' | 'diameter' | 'angle' | 'center-mark' | 'motor-envelope'
  const diameterSubMode = ref('line')  // 'line' (贯穿圆心直线) | 'leader' (引线折线)
  const angleSubMode = ref('edges')    // 'edges' (两条边夹角) | 'center' (顶点+两点的中心夹角)
  const centerSubMode = ref('single')  // 'single' (单孔十字) | 'group' (孔组:分度圆 + 各孔径向十字)
  const dimHoveredEdge = ref(null)   // { seg, transform, viewId, idx, type }
  const dimFirstEdge = ref(null)     // 第一选中边线
  const dimPending = ref(null)       // { mode, first, second } 已选齐对象，等点击固定
  const dimPreview = ref(null)       // 当前预览标注
  const dimensionColor = ref('#303133')
  const dimensionColorPresets = ['#303133', '#409eff', '#67c23a', '#e6a23c', '#f56c6c']
  const dimensions = ref([])         // 已放置标注
  const selectedDimId = ref(null)    // 选中标注 id
  const dimHoveredId = ref(null)     // 悬浮中的已放置标注 id(字符串,来自 data-dim-id)
  const dimDragging = ref(null)      // 拖拽调整中
  const dimIdCounter = { value: 0 }  // 按引用传给 core 自增

  function selectDim(id) {
    selectedDimId.value = id
    selectedViewId.value = null
  }

  const dimCore = coreFactory({
    getSheetPoint: coords.getSheetPoint,
    getViewDisplayScale: coords.getViewDisplayScale,
    getViewMmScale: coords.getViewMmScale,
    edgeRefData: coords.edgeRefData,
    getSvgMousePoint: coords.eventToSheetPoint,
    resolveDimRef: coords.resolveDimRef,
    // 屏幕 px → 图纸单位:引线预览偏移/限位等"屏幕 px 语义"常量的换算用
    screenPxToSheet: coords.screenPxToSheet,
    // 电机包络的 refs 只记 viewId(idx=-1),按 id 取视图,不能走 resolveDimRef
    findViewById: (id) => placedViews.value.find(v => v.id === id),
    getMotorEnvelope
  }, {
    dimensions,
    dimensionColor,
    idCounter: dimIdCounter,
    record: recordHistory
  })

  const {
    toggleTool, onDimEdgeSelect, onMotorEnvelopePick, updateDimPreviewAt, commitPendingLinear,
    commitAnglePoints, commitCenterMarkGroup, onCenterMarkGroupPick, pickCircleNear, pickBoltCircleNear,
    suppressPreviewAfterPlace,
    onDimMouseDown, onDimTextMouseDown, onDimExtensionHandleDown, onDimDragMove,
    onGlobalDimMouseUp, onKeyDown, clearDimState: clearDimToolState
  } = createDimEngine({
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
    getEdgeByRef: coords.getEdgeByRef,
    makeEdgeRef: coords.makeEdgeRef,
    resolveDimRef: coords.resolveDimRef,
    getSvgMousePoint: coords.eventToSheetPoint,
    getSheetPoint: coords.getSheetPoint,
    getMotorEnvelope,
    selectDim,
    selectView: (id) => { selectedViewId.value = id },
    core: dimCore,
    record: recordHistory,
    undo,
    redo
  })

  // ===== 撤销栈:快照已放置标注 + 选中态,Ctrl+Z 整体回退 =====
  const HISTORY_LIMIT = 50
  const undoStack = ref([])
  const redoStack = ref([])
  // 文本字段(自定义文字/标签)连续输入合并为一次撤销:记录首个按键前的快照,
  // 同一 (id,field) 的后续按键不再入栈,blur 后复位。否则每键一步、50 字吃满栈,
  // 撤销只能逐字回退。
  let fieldEditCtx = null

  function cloneDimensions() {
    // 标注对象均为纯 JSON 数据(refs/centerMarks 等嵌套数组),深拷贝隔离
    return JSON.parse(JSON.stringify(dimensions.value))
  }

  /** 记录当前状态到栈顶(在一次用户操作修改 dimensions 之前调用) */
  function recordHistory() {
    undoStack.value.push({ dims: cloneDimensions(), sel: selectedDimId.value })
    if (undoStack.value.length > HISTORY_LIMIT) undoStack.value.shift()
    // 新的修改分支使 redo 链失效:清空重做栈
    redoStack.value = []
    fieldEditCtx = null
  }

  function undo() {
    const snap = undoStack.value.pop()
    if (!snap) return
    // 撤销前把当前态压入重做栈,支持 Ctrl+Shift+Z / Ctrl+Y 重做
    redoStack.value.push({ dims: cloneDimensions(), sel: selectedDimId.value })
    dimensions.value = snap.dims.map(d => ({ ...d }))
    selectedDimId.value = snap.sel
    // 撤销后清掉进行中的临时选择,避免悬空态
    dimFirstEdge.value = null
    dimPending.value = null
    dimPreview.value = null
    dimDragging.value = null
    dimHoveredId.value = null
    fieldEditCtx = null
  }

  function redo() {
    const snap = redoStack.value.pop()
    if (!snap) return
    undoStack.value.push({ dims: cloneDimensions(), sel: selectedDimId.value })
    dimensions.value = snap.dims.map(d => ({ ...d }))
    selectedDimId.value = snap.sel
    dimFirstEdge.value = null
    dimPending.value = null
    dimPreview.value = null
    dimDragging.value = null
    dimHoveredId.value = null
    fieldEditCtx = null
  }

  const canUndo = computed(() => undoStack.value.length > 0)
  const canRedo = computed(() => redoStack.value.length > 0)

  const renderedDimensions = computed(() => dimensions.value
    .map(dim => dimCore.renderDimension(dim))
    .filter(Boolean)
  )

  const selectedDim = computed(() =>
    dimensions.value.find(d => d.id === selectedDimId.value) || null
  )

  /** 属性面板编辑标注字段(customText/label/bind_motor),直接改对象触发重渲染。
   *  文本字段每键触发:只在一段编辑的首次按键记录快照,后续按键合并,撤销时
   *  整段回退;开关字段(bind_motor)每次切换都是离散操作,必须每次都记录。 */
  function setDimField(id, field, value) {
    const dim = dimensions.value.find(d => d.id === id)
    if (!dim || dim[field] === value) return
    const isText = field === 'customText' || field === 'label'
    const sameCtx = fieldEditCtx && fieldEditCtx.id === id && fieldEditCtx.field === field
    if (!isText || !sameCtx) {
      recordHistory()
      if (isText) fieldEditCtx = { id, field }
    }
    dim[field] = value
  }

  /** 文本输入失焦:结束本次编辑会话,下次聚焦/输入再记一次快照 */
  function endFieldEdit() {
    fieldEditCtx = null
  }

  /** 标注右键菜单 */
  const dimContextMenu = ref(null)

  function openDimContextMenu(event, dim) {
    event.preventDefault()
    event.stopPropagation()
    selectDim(dim.id)
    dimContextMenu.value = {
      x: event.clientX,
      y: event.clientY,
      dimId: dim.id,
      currentMode: dim.arrowMode || 'auto'
    }
  }

  function closeDimContextMenu() {
    dimContextMenu.value = null
  }

  function setDimArrowMode(mode) {
    const m = dimContextMenu.value
    if (!m) return
    const dim = dimensions.value.find(d => d.id === m.dimId)
    if (dim) {
      recordHistory()
      dim.arrowMode = mode
    }
    closeDimContextMenu()
  }

  /** 待高亮的选中对象：第一边 + 待固定态的第二边，附带圆拟合与图纸坐标半径 */
  const dimHighlightEdges = computed(() => {
    const list = []
    if (dimFirstEdge.value) list.push(dimFirstEdge.value)
    if (dimPending.value?.second) list.push(dimPending.value.second)
    // 中心夹角的选择态:顶点与已选被测点所属对象都要高亮
    if (dimPending.value?.mode === 'angle-points') {
      const refs = [dimPending.value.vertexRef, ...(dimPending.value.points || [])]
      for (const ref of refs) {
        const edge = ref ? coords.resolveDimRef(ref) : null
        if (edge) list.push(edge)
      }
    }
    return list.map(edge => {
      const circle = toCircle(edge.seg)
      const r = circle ? circle.r * coords.getViewDisplayScale(edge.view) : null
      return { edge, circle, r }
    })
  })

  /** 点击图纸空白:清除临时选择(保留已放置标注) */
  function clearTransientSelection() {
    dimFirstEdge.value = null
    dimPending.value = null
    dimPreview.value = null
    selectedDimId.value = null
  }

  /** SVG mousedown:标注工具激活时的边线选择/放置/取消 */
  function onSvgMouseDown(event) {
    if (!activeTool.value) return
    // 直径/中心标记:先做分度圆几何择近命中(与 hover 预览同一判定)。
    // 必须在 DOM 命中之前——孔都长在分度圆周上,DOM 命中带会先抓到孔,
    // 否则"预览按分度圆、点击却落在孔"行为分裂。
    // 命中分度圆=对分度圆做直径标注(PCD)/在孔组中心打十字,引用整组孔,
    // 换型号后位置自动跟随
    if (activeTool.value === 'diameter' || activeTool.value === 'center-mark') {
      const pt = coords.eventToSheetPoint(event)
      const bolt = pickBoltCircleNear(pt)
      if (bolt) {
        const hole = pickCircleNear(pt)
        if (!hole || bolt.d <= hole.d) {
          recordHistory()
          let id
          if (activeTool.value === 'diameter') {
            const pv = dimPreview.value
            // 回退偏移"鼠标左侧60屏幕px"按画布缩放折算(sheet单位)
            const su = dimCore.sheetPerScreenPx()
            id = dimCore.placeDiameterOnBoltCircleDim(bolt.dim.refs,
              diameterSubMode.value === 'leader'
                ? { mode: 'leader', textLeft: pv?.textPos || (pt ? { x: pt.x - 60 * su, y: pt.y } : null),
                    leaderAngle: pv?.leaderAngle }
                : { leaderAngle: pv?.leaderAngle })
          } else {
            id = dimCore.placeCenterMarkAtGroupCenter(bolt.dim.refs)
          }
          if (id) {
            selectDim(id)
            suppressPreviewAfterPlace(pt)
          }
          return
        }
      }
    }
    const target = document.elementFromPoint(event.clientX, event.clientY)
    const hit = target && target.closest ? target.closest('[data-dim-view]') : null
    if (hit) {
      onDimEdgeSelect(hit, event)
      return
    }
    // 点击空白处：已选齐对象的预览就地落位
    if (activeTool.value === 'linear' && dimPending.value) {
      commitPendingLinear()
      return
    }
    // 中心夹角:三点选齐后点空白按当前半径落位(未选齐则继续走清空分支)
    if (activeTool.value === 'angle' && commitAnglePoints()) return
    // 中心标记(单孔/孔组共用):DOM 命中带未覆盖时按几何兜底就近找孔
    // (分度圆已在函数开头择近处理,这里只管孔)
    if (activeTool.value === 'center-mark') {
      const pt = coords.eventToSheetPoint(event)
      const hole = pickCircleNear(pt)
      if (hole) {
        if (centerSubMode.value === 'group') {
          onCenterMarkGroupPick(hole)
          return
        }
        recordHistory()
        const id = dimCore.placeCenterMarkDim(hole)
        if (id) selectDim(id)
        return
      }
      // 孔与分度圆都没命中:孔组模式保留已选的孔(要清按 Esc),选够了就地落位
      if (centerSubMode.value === 'group') {
        if (commitCenterMarkGroup()) return
        return
      }
    }
    // 只选了一根边线：单边标注按当前偏移直接放置
    const first = dimFirstEdge.value
    const preview = dimPreview.value
    if (activeTool.value === 'linear' && first && preview && toLineSeg(first.seg) && preview.type === 'linear' && preview.mode === 'single') {
      const offset = preview.offset ?? dimCore.getLinearOffsetFromMouse(first, coords.eventToSheetPoint(event))
      recordHistory()
      const id = dimCore.placeLinearDimSingle(first, offset)
      if (id) selectDim(id)
      dimFirstEdge.value = null
      dimPreview.value = null
      dimHoveredEdge.value = null
      activeTool.value = null
      return
    }
    clearTransientSelection()
  }

  /** 鼠标移出图纸:清掉 hover 高亮,避免残留 */
  function onSvgMouseLeave() {
    dimHoveredId.value = null
    if (dimHoveredEdge.value) dimHoveredEdge.value = null
  }

  /** 点击已放置标注:选中它;标注工具激活时同步退出其临时选择态(第一边/待固定预览) */
  function onDimClick(dim) {
    selectDim(dim.id)
    if (activeTool.value) clearDimToolState()
  }

  /** SVG mousemove:先看是否悬浮在已放置标注上,否则走透明命中层的边线 hover + 预览更新 */
  function onSvgMouseMove(event) {
    // 已放置标注优先：无论是普通模式还是标注工具激活时,都要能悬浮高亮并点击选中。
    // 命中时冻结预览(不跟随鼠标),否则待固定态的预览会在用户去点标注时乱跳。
    const target = document.elementFromPoint(event.clientX, event.clientY)
    const hitDimEl = target?.closest('[data-dim-id]')
    if (hitDimEl) {
      dimHoveredId.value = hitDimEl.dataset.dimId
      if (dimHoveredEdge.value) dimHoveredEdge.value = null
      return
    }
    if (dimHoveredId.value) dimHoveredId.value = null

    if (!activeTool.value) return

    // 电机包络:与具体边线无关,鼠标进入视图范围即按该视图的包络出预览
    if (activeTool.value === 'motor-envelope') {
      const pt = coords.eventToSheetPoint(event)
      const v = pt ? coords.findViewAtPoint(pt) : null
      const env = v && getMotorEnvelope ? getMotorEnvelope(v) : null
      if (v && env) {
        if (dimHoveredEdge.value?.viewId !== v.id) {
          // 视图级 hover:只记录落在哪个视图上,没有对应边线。seg 显式置 null,
          // 渲染层据此跳过边线高亮(否则读 seg.type 会抛错白屏)。
          dimHoveredEdge.value = { view: v, viewId: v.id, seg: null, motorEnvelope: true }
        }
        updateDimPreviewAt(event)
      } else {
        if (dimHoveredEdge.value) dimHoveredEdge.value = null
        if (dimPreview.value) dimPreview.value = null
      }
      return
    }

    const hit = target?.closest('[data-dim-view]') ?? null
    if (hit) {
      const viewId = hit.dataset.dimView
      const idx = parseInt(hit.dataset.dimIdx, 10)
      const type = hit.dataset.dimType
      const seg = coords.getEdgeByRef(viewId, idx, type)
      const view = placedViews.value.find(v => v.id === viewId)
      if (seg && view) {
        const hover = coords.makeEdgeRef(view, idx, type, seg)
        // 引用不同才更新(避免重复 set)
        const cur = dimHoveredEdge.value
        if (!cur || cur.viewId !== viewId || cur.idx !== idx || cur.type !== type) {
          dimHoveredEdge.value = hover
        }
        updateDimPreviewAt(event)
        return
      }
    }
    // 直径/中心标记工具:分度圆几何 hover(与 mousedown 同一"择近"判定)。
    // DOM 命中带让路给孔,分度圆虚线 1px 极难点中,靠几何兜底高亮孔组标注
    // (虚线变蓝给出瞄准反馈),预览由引擎按分度圆生成(择近);
    // 鼠标更靠近孔时让位给孔的既有 DOM hover/预览通道
    if (activeTool.value === 'center-mark' || activeTool.value === 'diameter') {
      const pt = coords.eventToSheetPoint(event)
      const bolt = pickBoltCircleNear(pt)
      if (bolt) {
        const hole = pickCircleNear(pt)
        if (!hole || bolt.d <= hole.d) {
          dimHoveredId.value = String(bolt.dim.id)
          if (dimHoveredEdge.value) dimHoveredEdge.value = null
          updateDimPreviewAt(event)
          return
        }
      }
    }
    if (dimHoveredEdge.value) dimHoveredEdge.value = null
    updateDimPreviewAt(event)
  }

  /** 删除引用了指定视图的全部标注 */
  function removeByView(viewId) {
    dimensions.value = dimensions.value.filter(
      dim => !(dim.refs || []).some(ref => ref.viewId === viewId)
    )
  }

  /** 全量重置(清空图纸时) */
  function resetAll() {
    dimensions.value = []
    selectedDimId.value = null
    dimHoveredId.value = null
    dimHoveredEdge.value = null
    dimFirstEdge.value = null
    dimPending.value = null
    dimPreview.value = null
    undoStack.value = []
    redoStack.value = []
    fieldEditCtx = null
  }

  /** 从源文件批量载入标注 */
  function setDimensions(dims) {
    dimensions.value = (dims || []).map(d => ({ ...d }))
    selectedDimId.value = null
    dimHoveredId.value = null
    undoStack.value = []
    redoStack.value = []
    fieldEditCtx = null
  }

  return {
    activeTool, diameterSubMode, angleSubMode, centerSubMode,
    dimHoveredEdge, dimFirstEdge, dimPending, dimPreview,
    dimensionColor, dimensionColorPresets, dimensions, selectedDimId, dimDragging,
    renderedDimensions, dimHighlightEdges, dimHoveredId, selectedDim, setDimField,
    setDimensions,
    dimContextMenu, openDimContextMenu, closeDimContextMenu, setDimArrowMode,
    toggleTool, onDimEdgeSelect, onMotorEnvelopePick, onDimMouseDown, onDimTextMouseDown,
    onDimExtensionHandleDown, onDimDragMove,
    onGlobalDimMouseUp, onKeyDown, selectDim, onDimClick,
    onSvgMouseDown, onSvgMouseMove, onSvgMouseLeave,
    clearTransientSelection, removeByView, resetAll, undo, redo, canUndo, canRedo,
    endFieldEdit
  }
}
