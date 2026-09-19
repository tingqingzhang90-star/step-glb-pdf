<template>
  <div class="sw-drawing-app">
    <template v-if="!viewMode">
      <header class="top-toolbar">
      <div class="toolbar-left">
        <span class="app-title">工程图编辑器</span>
        <el-divider direction="vertical" />
        <el-select v-model="selectedModel" placeholder="选择型号" filterable size="small" class="model-select" @change="onModelChange">
          <el-option v-for="m in models" :key="m" :label="m" :value="m" />
        </el-select>
        <el-button type="primary" size="small" :loading="loadingViews" :disabled="!selectedModel" @click="loadViewPalette">
          <el-icon><Upload /></el-icon>
          导入模型
        </el-button>
        <el-divider direction="vertical" />
        <el-button size="small" :disabled="!placedViews.length" @click="exportDrawingDocument">导出源文件</el-button>
        <el-button size="small" type="primary" :loading="exportingPdf" :disabled="!placedViews.length" @click="exportPdf">导出 PDF</el-button>
        <el-select
          v-model="selectedSource"
          placeholder="导入源文件"
          size="small"
          filterable
          clearable
          :loading="loadingSources"
          style="width: 168px"
          title="从 output 目录已生成的源文件选择"
          @change="onSourcePicked"
        >
          <el-option
            v-for="s in sourceOptions"
            :key="s.name"
            :label="s.name + (s.sheet ? ` (${s.sheet})` : '')"
            :value="s.name"
          />
        </el-select>
        <el-button size="small" :icon="Refresh" :loading="loadingSources" title="刷新源文件列表" @click="loadSourceList" />
        <el-button size="small" @click="triggerImportDoc" title="从本地文件导入">本地导入</el-button>
        <input ref="fileInputRef" type="file" accept=".json,application/json" style="display:none" @change="onFilePicked" />
      </div>

      <div class="toolbar-center">
        <el-select v-model="sheetSize" size="small" style="width: 80px" :disabled="!viewsLoaded" @change="onSheetSizeChange" title="图纸幅面">
          <el-option v-for="s in sheetSizeOptions" :key="s" :label="s" :value="s" />
        </el-select>
        <el-divider direction="vertical" />
        <el-button-group>
          <el-button size="small" :icon="ZoomIn" :disabled="!viewsLoaded" @click="zoomCanvas(1.2)">放大</el-button>
          <el-button size="small" :icon="ZoomOut" :disabled="!viewsLoaded" @click="zoomCanvas(0.8)">缩小</el-button>
          <el-button size="small" :disabled="!viewsLoaded" @click="resetCanvas">适应</el-button>
        </el-button-group>
        <div class="mobile-hide">
        <el-divider direction="vertical" />
        <el-button-group>
          <el-button size="small" :type="activeTool === 'linear' ? 'primary' : ''" :disabled="!viewsLoaded" @click="toggleTool('linear')">线性</el-button>
          <el-button size="small" :type="activeTool === 'diameter' ? 'primary' : ''" :disabled="!viewsLoaded" @click="toggleTool('diameter')">直径</el-button>
          <el-dropdown v-if="activeTool === 'diameter'" trigger="click" @command="(cmd) => diameterSubMode = cmd">
            <el-button size="small">{{ diameterSubMode === 'leader' ? '引线' : '直线' }}<el-icon class="el-icon--right"><ArrowDown /></el-icon></el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="line">直线(贯穿圆心)</el-dropdown-item>
                <el-dropdown-item command="leader">引线(折线标注)</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <el-button size="small" :type="activeTool === 'angle' ? 'primary' : ''" :disabled="!viewsLoaded" @click="toggleTool('angle')">角度</el-button>
          <el-button size="small" :type="activeTool === 'center-mark' ? 'primary' : ''" :disabled="!viewsLoaded" @click="toggleTool('center-mark')">中心</el-button>
          <el-button size="small" :type="activeTool === 'motor-envelope' ? 'primary' : ''" :disabled="!viewsLoaded" @click="toggleTool('motor-envelope')">电机包络</el-button>
        </el-button-group>
        <el-color-picker v-model="dimensionColor" size="small" :predefine="dimensionColorPresets" aria-label="标注颜色" />
        <el-divider direction="vertical" />
        <el-popover trigger="click" :width="320" placement="bottom-start" v-model:visible="showTablePicker">
          <template #reference>
            <el-button size="small" :icon="DocumentAdd">插入表格</el-button>
          </template>
          <TableSizePicker :max-rows="20" :max-cols="20" :cell="14" @confirm="onPickTableSize" />
        </el-popover>
        <el-button size="small" :disabled="!placedTables.length" @click="onSaveTablePreset">存为表格模板</el-button>
        <el-dropdown v-if="tablePresets.length" trigger="click" @command="onApplyTablePreset">
          <el-button size="small">
            表格模板<el-icon class="el-icon--right"><ArrowDown /></el-icon>
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item v-for="p in tablePresets" :key="p.id" :command="p.id">
                <span class="preset-row">
                  <span class="preset-name">{{ p.name }}</span>
                  <el-icon class="preset-del" @click.stop="onRemoveTablePreset(p.id)"><Delete /></el-icon>
                </span>
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <el-button size="small" :disabled="selectedCells.length < 2" @click="mergeSelected">合并</el-button>
        <el-button size="small" :disabled="selectedCells.length !== 1" @click="splitSelected">取消合并</el-button>
        <el-popover trigger="click" :width="230" v-model:visible="showSplitPicker">
          <template #reference>
            <el-button size="small" :disabled="selectedCells.length !== 1">拆分单元格</el-button>
          </template>
          <div class="split-picker">
            <el-radio-group v-model="splitDir" size="small">
              <el-radio-button label="h">横向(左右)</el-radio-button>
              <el-radio-button label="v">纵向(上下)</el-radio-button>
            </el-radio-group>
            <div class="split-count-row">
              <span>份数</span>
              <el-input-number v-model="splitCount" :min="2" :max="20" size="small" />
            </div>
            <el-button type="primary" size="small" class="split-apply" @click="applySplit">确定拆分</el-button>
          </div>
        </el-popover>
        <TableStyleBar
          :selected-id="selectedTableId"
          :selected-cells="selectedCells"
          :font-size="selectedCellFontSize"
          :cell-color="selectedCellColor"
          :border-width="selectedTable?.border?.width ?? 0.3"
          :border-color="selectedTable?.border?.color ?? '#303133'"
          @font-size="setFontOfSelected"
          @cell-color="setColorOfSelected"
          @border-width="setBorderWidth"
          @border-color="setBorderColor"
        />
        <el-button size="small" type="danger" :icon="Delete" :disabled="!selectedTableId" @click="removeSelectedTable">删表</el-button>
        <el-divider direction="vertical" />
        <el-button size="small" :icon="Delete" :disabled="placedViews.length === 0" @click="clearPlacedViews">清空</el-button>
        </div>
      </div>

      <div class="toolbar-right mobile-hide">
        <span v-if="loadingText" class="status-text">{{ loadingText }}</span>
        <span v-if="lastElapsed" class="status-ok">耗时 {{ lastElapsed }}s</span>
        <span v-if="error" class="status-err">{{ error }}</span>
      </div>
    </header>
    </template>

    <header v-if="viewMode" class="top-toolbar view-toolbar">
      <div class="toolbar-left">
        <span class="app-title">工程图预览</span>
        <el-divider direction="vertical" />
        <el-button-group>
          <el-button size="small" :icon="ZoomIn" :disabled="!viewerReady" @click="zoomCanvas(1.2)">放大</el-button>
          <el-button size="small" :icon="ZoomOut" :disabled="!viewerReady" @click="zoomCanvas(0.8)">缩小</el-button>
          <el-button size="small" :disabled="!viewerReady" @click="resetCanvas">适应</el-button>
        </el-button-group>
        <span v-if="viewLoading" class="status-text">加载中...</span>
        <span v-else-if="selectedModel" class="status-text">{{ selectedModel }}</span>
        <span v-if="viewError" class="status-err">{{ viewError }}</span>
      </div>
      <div class="toolbar-right">
        <el-button size="small" type="primary" :loading="exportingPdf" :disabled="!viewerReady" @click="exportPdf">导出 PDF</el-button>
      </div>
    </header>

    <main class="editor-shell" :class="{ 'view-mode': viewMode }">
      <aside v-if="!viewMode" class="view-palette">
        <div class="panel-header">视图调色板</div>

        <div v-if="loadingViews" class="panel-empty">
          <el-icon class="is-loading"><Loading /></el-icon>
          <p>正在生成视图...</p>
          <p class="sub">STEP → HLR 投影 → 标准视图</p>
        </div>

        <div v-else-if="!viewsLoaded" class="panel-empty">
          <p>请先导入模型</p>
        </div>

        <template v-else>
          <section class="palette-section">
            <div class="section-title">标准视图</div>
            <div class="view-grid">
              <div
                v-for="vw in standardViews"
                :key="vw.name"
                :class="['view-item', { 'is-placed': placedViewNames.has(vw.name) }]"
                :title="placedViewNames.has(vw.name) ? `「${vw.label}」已放置` : `点击或拖拽放置「${vw.label}」`"
                @pointerdown="!placedViewNames.has(vw.name) && onPalettePointerDown($event, vw)"
              >
                <div class="view-thumbnail" v-html="vw.thumbnail"></div>
                <span class="view-label">{{ vw.label }}</span>
              </div>
            </div>
          </section>

          <section class="palette-section">
            <div class="section-title">轴测视图</div>
            <div class="view-grid">
              <div
                v-for="vw in isometricViews"
                :key="vw.name"
                :class="['view-item', { 'is-placed': placedViewNames.has(vw.name) }]"
                :title="placedViewNames.has(vw.name) ? `「${vw.label}」已放置` : `点击或拖拽放置「${vw.label}」`"
                @pointerdown="!placedViewNames.has(vw.name) && onPalettePointerDown($event, vw)"
              >
                <div class="view-thumbnail" v-html="vw.thumbnail"></div>
                <span class="view-label">{{ vw.label }}</span>
              </div>
            </div>
          </section>
        </template>
        <SymbolPalette
          :dragging-file="symbolDraggingFile"
          :preview-pos="symbolPreviewPos"
          @symbol-pointerdown="onSymbolPointerDown"
        />
      </aside>

      <section class="canvas-region">
        <div class="sheet-area" ref="sheetAreaRef">
          <div class="sheet-grid"></div>
          <svg
            ref="svgRef"
            :class="['drawing-sheet', { 'dim-active': activeTool }]"
            :width="sheetWidth * sheetZoom"
            :height="sheetHeight * sheetZoom"
            :viewBox="`0 0 ${sheetWidth} ${sheetHeight}`"
            :style="sheetCardStyle"
            @wheel="onSheetWheel"
            @mousedown="onSvgMouseDown"
            @mousemove="onSvgMouseMove"
            @mouseleave="onSvgMouseLeave"
          >
            <rect x="20" y="20" :width="sheetWidth - 40" :height="sheetHeight - 40" fill="#ffffff" stroke="#999" stroke-width="1" />
            <rect x="920" y="690" width="240" height="120" fill="none" stroke="#555" stroke-width="1" />
            <line x1="920" y1="730" x2="1160" y2="730" stroke="#555" stroke-width="1" />
            <line x1="1000" y1="690" x2="1000" y2="810" stroke="#555" stroke-width="1" />
            <text x="1040" y="715" font-size="18" fill="#303133">产品工程图</text>
            <text x="936" y="755" font-size="12" fill="#606266">型号</text>
            <text x="1016" y="755" font-size="12" fill="#303133">{{ selectedModel || '-' }}</text>

            <!-- 对齐引导线（仅拖拽时显示） -->
            <g v-if="alignmentGuides.length > 0" class="alignment-guides" pointer-events="none">
              <template v-for="(guide, i) in alignmentGuides" :key="`guide-${i}`">
                <line
                  v-if="guide.type === 'vertical'"
                  :x1="guide.pos" y1="20" :x2="guide.pos" :y2="sheetHeight - 20"
                  stroke="#409eff" stroke-width="1" stroke-dasharray="6,3"
                  vector-effect="non-scaling-stroke" opacity="0.7"
                />
                <line
                  v-else
                  x1="20" :y1="guide.pos" :x2="sheetWidth - 20" :y2="guide.pos"
                  stroke="#409eff" stroke-width="1" stroke-dasharray="6,3"
                  vector-effect="non-scaling-stroke" opacity="0.7"
                />
              </template>
            </g>

            <g
              v-for="pv in placedViews"
              :key="pv.id"
              :transform="`translate(${pv.x}, ${pv.y}) scale(${getViewDisplayScale(pv)})`"
              :class="['placed-view', { selected: selectedViewId === pv.id }]"
              @mousedown.stop="onViewMouseDown($event, pv)"
              @click.stop="selectView(pv.id)"
            >
              <!-- 命中底板:SVG 默认只有描边参与命中,图形内部空白点不到;
                   铺一层透明可命中矩形,让整个视图范围都能选中与拖动。
                   标注工具激活时必须让路,否则事件被本组 .stop 拦截,
                   SVG 根上的标注落位逻辑收不到点击 -->
              <rect
                :x="pv.contentBBox.x - 4"
                :y="pv.contentBBox.y - 4"
                :width="pv.contentBBox.width + 8"
                :height="pv.contentBBox.height + 8"
                fill="transparent"
                :pointer-events="activeTool ? 'none' : 'all'"
              />
              <rect
                :x="pv.contentBBox.x - 4"
                :y="pv.contentBBox.y - 4"
                :width="pv.contentBBox.width + 8"
                :height="pv.contentBBox.height + 8"
                fill="none"
                :stroke="selectedViewId === pv.id ? '#409eff' : 'transparent'"
                stroke-width="2"
                stroke-dasharray="4,2"
                vector-effect="non-scaling-stroke"
              />
              <g class="visible-edges" vector-effect="non-scaling-stroke" stroke-width="1">
                <template v-for="(seg, i) in pv.edges" :key="`v${i}`">
                  <line
                    v-if="seg && seg.type === 'line'"
                    :x1="seg.x1"
                    :y1="seg.y1"
                    :x2="seg.x2"
                    :y2="seg.y2"
                    stroke="#333"
                    vector-effect="non-scaling-stroke"
                  />
                  <circle
                    v-else-if="seg && seg.type === 'circle'"
                    :cx="seg.cx"
                    :cy="seg.cy"
                    :r="seg.r"
                    stroke="#333"
                    fill="none"
                    vector-effect="non-scaling-stroke"
                  />
                  <polyline
                    v-else-if="seg && seg.type === 'polyline'"
                    :points="polylinePoints(seg.points)"
                    stroke="#333"
                    fill="none"
                    vector-effect="non-scaling-stroke"
                  />
                </template>
              </g>
              <g class="hidden-edges" vector-effect="non-scaling-stroke">
                <template v-for="(seg, i) in pv.hiddenEdges" :key="`h${i}`">
                  <line
                    v-if="seg && seg.type === 'line'"
                    :x1="seg.x1"
                    :y1="seg.y1"
                    :x2="seg.x2"
                    :y2="seg.y2"
                    stroke="#999"
                    stroke-width="0.8"
                    stroke-dasharray="3,2"
                    vector-effect="non-scaling-stroke"
                  />
                </template>
              </g>
            </g>

            <!-- 已放置表格:渲染与交互抽离到 TableLayer,吸附引导线独立组件 -->
            <TableLayer
              :tables="placedTables"
              :selected-id="selectedTableId"
              :selected-cells="selectedCells"
              :editing-cell="editingCell"
              :hover-cell="hoverCell"
              :readonly="viewMode"
              :snap-guides="tableSnapGuides"
              @table-mousedown="onTableMouseDown"
              @cell-click="onCellClick"
              @cell-mousedown="onCellMouseDown"
              @cell-mouseenter="onCellMouseEnter"
              @cell-mouseleave="clearHover"
              @cell-dblclick="onCellDblClick"
              @cell-contextmenu="openContextMenu"
              @corner-mousedown="startCornerResize"
              @col-mousedown="startColResize"
              @row-mousedown="startRowResize"
              @edit-commit="commitEdit"
              @edit-cancel="cancelEdit"
            />
            <TableSnapGuides
              :guides="tableSnapGuides"
              :sheet-width="sheetWidth"
              :sheet-height="sheetHeight"
            />

            <!-- 标注命中层（仅标注工具激活时） -->
            <g v-if="activeTool" class="dim-hit-layer" pointer-events="stroke">
              <!-- 电机包络:视图级透明命中区(仅该工具激活时)。
                   电机包络取自后端包络数据、与具体边线无关,
                   因此按整个视图区域命中:悬浮即出预览,点击即落位。 -->
              <g v-if="activeTool === 'motor-envelope'" class="dim-hit-motor">
                <template v-for="pv in placedViews" :key="'motor-'+pv.id">
                  <rect
                    :x="viewSheetRect(pv).x" :y="viewSheetRect(pv).y"
                    :width="viewSheetRect(pv).width" :height="viewSheetRect(pv).height"
                    fill="transparent" pointer-events="all"
                    @mousedown.stop="onMotorEnvelopePick($event, pv)"
                  />
                </template>
              </g>
              <!-- 已放置标注的命中副本(只在标注模式下存在)。
                   真实可见的 .dimension-group 此时 .dim-hit-stroke 让路给边线,
                   由这里统一提供命中——已放置标注与模型边线共享同一命中层,
                   不再有 12px 命中带互相遮挡的问题。
                   命中事件在外层 g 上统一捕获,通过 data-dim-id 反查 dim 路由到
                   onDimMouseDown/onDimClick。
                   
                   z-order 策略:
                     - "等第二边" 状态(dimFirstEdge 已选、待固定态还没建立)时
                       把本组放到 view 命中层 之前,让边线命中优先级高于已放置标注,
                       避免已放置标注的 10px 命中带挡住底层的边线。
                     - 其他时候放回 view 之后,已放置标注可正常点中。 -->
              <g v-if="dimFirstEdge && !dimPending" class="dim-hit-dims" style="pointer-events:none">
                <template v-for="dim in renderedDimensions" :key="`ddh-${dim.id}`">
                  <template v-if="dim.type === 'linear'">
                    <line :x1="dim.ext1.x" :y1="dim.ext1.y" :x2="dim.ext1End.x" :y2="dim.ext1End.y" class="dim-hit-line" :data-dim-id="dim.id" />
                    <line :x1="dim.ext2.x" :y1="dim.ext2.y" :x2="dim.ext2End.x" :y2="dim.ext2End.y" class="dim-hit-line" :data-dim-id="dim.id" />
                    <line :x1="dim.dimLineStart.x" :y1="dim.dimLineStart.y" :x2="dim.dimLineEnd.x" :y2="dim.dimLineEnd.y" class="dim-hit-line" :data-dim-id="dim.id" />
                    <template v-for="(cm, ci) in dim.centerMarks || []" :key="`ddh-cm-${dim.id}-${ci}`">
                      <line :x1="cm.x - cm.r" :y1="cm.y" :x2="cm.x + cm.r" :y2="cm.y" class="dim-hit-line" :data-dim-id="dim.id" />
                      <line :x1="cm.x" :y1="cm.y - cm.r" :x2="cm.x" :y2="cm.y + cm.r" class="dim-hit-line" :data-dim-id="dim.id" />
                    </template>
                  </template>
                  <template v-else-if="dim.type === 'diameter'">
                    <line :x1="dim.leaderStart.x" :y1="dim.leaderStart.y" :x2="dim.leaderEnd.x" :y2="dim.leaderEnd.y" class="dim-hit-line" :data-dim-id="dim.id" />
                  </template>
                  <template v-else-if="dim.type === 'angle'">
                    <path :d="dim.arcPath" class="dim-hit-line" :data-dim-id="dim.id" />
                  </template>
                  <template v-else-if="dim.type === 'center-mark'">
                    <template v-for="(cm, ci) in dim.centerMarks || []" :key="`ddh-cmk-${dim.id}-${ci}`">
                      <line :x1="cm.x - cm.r" :y1="cm.y" :x2="cm.x + cm.r" :y2="cm.y" class="dim-hit-line" :data-dim-id="dim.id" />
                      <line :x1="cm.x" :y1="cm.y - cm.r" :x2="cm.x" :y2="cm.y + cm.r" class="dim-hit-line" :data-dim-id="dim.id" />
                    </template>
                  </template>
                </template>
              </g>
              <g v-for="pv in placedViews" :key="'hit-'+pv.id" :transform="`translate(${pv.x}, ${pv.y}) scale(${getViewDisplayScale(pv)})`">
                <template v-for="(seg, i) in pv.edges" :key="`dvh-${i}`">
                  <line v-if="seg.type === 'line' && activeTool !== 'diameter'" :x1="seg.x1" :y1="seg.y1" :x2="seg.x2" :y2="seg.y2" fill="none" vector-effect="non-scaling-stroke" class="dim-hit-line" :data-dim-view="pv.id" :data-dim-idx="i" :data-dim-type="'edges'" />
                  <polyline v-else-if="seg.type === 'polyline'" :points="polylinePoints(seg.points)" fill="none" vector-effect="non-scaling-stroke" class="dim-hit-line" :data-dim-view="pv.id" :data-dim-idx="i" :data-dim-type="'edges'" />
                  <circle v-else-if="seg.type === 'circle' && circleHitTools.includes(activeTool)" :cx="seg.cx" :cy="seg.cy" :r="seg.r" fill="none" vector-effect="non-scaling-stroke" class="dim-hit-circle" :data-dim-view="pv.id" :data-dim-idx="i" :data-dim-type="'edges'" />
                </template>
                <template v-for="(seg, i) in pv.hiddenEdges" :key="`dvh-h-${i}`">
                  <line v-if="seg.type === 'line' && activeTool !== 'diameter'" :x1="seg.x1" :y1="seg.y1" :x2="seg.x2" :y2="seg.y2" fill="none" vector-effect="non-scaling-stroke" class="dim-hit-line" :data-dim-view="pv.id" :data-dim-idx="i" :data-dim-type="'hiddenEdges'" />
                  <polyline v-else-if="seg.type === 'polyline'" :points="polylinePoints(seg.points)" fill="none" vector-effect="non-scaling-stroke" class="dim-hit-line" :data-dim-view="pv.id" :data-dim-idx="i" :data-dim-type="'hiddenEdges'" />
                  <circle v-else-if="seg.type === 'circle' && circleHitTools.includes(activeTool)" :cx="seg.cx" :cy="seg.cy" :r="seg.r" fill="none" vector-effect="non-scaling-stroke" class="dim-hit-circle" :data-dim-view="pv.id" :data-dim-idx="i" :data-dim-type="'hiddenEdges'" />
                </template>
              </g>
              <g v-if="!dimFirstEdge || dimPending" class="dim-hit-dims" @mousedown.stop="onDimHitMouseDown" @click.stop="onDimHitClick">
                <template v-for="dim in renderedDimensions" :key="`ddh-${dim.id}`">
                  <template v-if="dim.type === 'linear'">
                    <line :x1="dim.ext1.x" :y1="dim.ext1.y" :x2="dim.ext1End.x" :y2="dim.ext1End.y" class="dim-hit-line" :data-dim-id="dim.id" />
                    <line :x1="dim.ext2.x" :y1="dim.ext2.y" :x2="dim.ext2End.x" :y2="dim.ext2End.y" class="dim-hit-line" :data-dim-id="dim.id" />
                    <line :x1="dim.dimLineStart.x" :y1="dim.dimLineStart.y" :x2="dim.dimLineEnd.x" :y2="dim.dimLineEnd.y" class="dim-hit-line" :data-dim-id="dim.id" />
                    <template v-for="(cm, ci) in dim.centerMarks || []" :key="`ddh-cm-${dim.id}-${ci}`">
                      <line :x1="cm.x - cm.r" :y1="cm.y" :x2="cm.x + cm.r" :y2="cm.y" class="dim-hit-line" :data-dim-id="dim.id" />
                      <line :x1="cm.x" :y1="cm.y - cm.r" :x2="cm.x" :y2="cm.y + cm.r" class="dim-hit-line" :data-dim-id="dim.id" />
                    </template>
                  </template>
                  <template v-else-if="dim.type === 'diameter'">
                    <line :x1="dim.leaderStart.x" :y1="dim.leaderStart.y" :x2="dim.leaderEnd.x" :y2="dim.leaderEnd.y" class="dim-hit-line" :data-dim-id="dim.id" />
                  </template>
                  <template v-else-if="dim.type === 'angle'">
                    <path :d="dim.arcPath" class="dim-hit-line" :data-dim-id="dim.id" />
                  </template>
                  <template v-else-if="dim.type === 'center-mark'">
                    <template v-for="(cm, ci) in dim.centerMarks || []" :key="`ddh-cmk-${dim.id}-${ci}`">
                      <line :x1="cm.x - cm.r" :y1="cm.y" :x2="cm.x + cm.r" :y2="cm.y" class="dim-hit-line" :data-dim-id="dim.id" />
                      <line :x1="cm.x" :y1="cm.y - cm.r" :x2="cm.x" :y2="cm.y + cm.r" class="dim-hit-line" :data-dim-id="dim.id" />
                    </template>
                  </template>
                </template>
              </g>
            </g>

            <!-- 标注高亮层（hover/选中边线） -->
            <g v-if="activeTool && dimHoveredEdge" class="dim-highlight" pointer-events="none">
              <g :transform="dimHoveredEdge.transform">
                <line v-if="dimHoveredEdge.seg.type === 'line'" :x1="dimHoveredEdge.seg.x1" :y1="dimHoveredEdge.seg.y1" :x2="dimHoveredEdge.seg.x2" :y2="dimHoveredEdge.seg.y2" class="dim-highlight-hover" />
                <circle v-else-if="dimHoveredEdge.seg.type === 'circle'" :cx="dimHoveredEdge.seg.cx" :cy="dimHoveredEdge.seg.cy" :r="dimHoveredEdge.seg.r" class="dim-highlight-hover" />
                <polyline v-else-if="dimHoveredEdge.seg.type === 'polyline'" :points="polylinePoints(dimHoveredEdge.seg.points)" class="dim-highlight-hover" />
              </g>
            </g>
            <g v-for="(item, ei) in dimHighlightEdges" :key="'sel-' + ei" class="dim-highlight" pointer-events="none">
              <g :transform="item.edge.transform">
                <line v-if="item.edge.seg.type === 'line'" :x1="item.edge.seg.x1" :y1="item.edge.seg.y1" :x2="item.edge.seg.x2" :y2="item.edge.seg.y2" class="dim-highlight-selected" />
                <template v-else-if="item.circle">
                  <circle :cx="item.circle.cx" :cy="item.circle.cy" :r="item.circle.r" class="dim-highlight-selected" />
                  <g class="dim-center-mark" :transform="`translate(${item.circle.cx}, ${item.circle.cy})`">
                    <line :x1="-(item.r || 8)" y1="0" :x2="item.r || 8" y2="0" />
                    <line x1="0" :y1="-(item.r || 8)" x2="0" :y2="item.r || 8" />
                  </g>
                </template>
                <polyline v-else-if="item.edge.seg.type === 'polyline'" :points="polylinePoints(item.edge.seg.points)" class="dim-highlight-selected" />
              </g>
            </g>

            <!-- 标注预览 -->
            <g v-if="dimPreview" :class="['dim-preview', { 'dim-preview-pending': !!dimPending }]" :style="{ '--dimension-color': dimensionColor }" pointer-events="none">
              <template v-if="dimPreview.type === 'linear' || dimPreview.type === 'center-mark'">
                <g v-for="(cm, ci) in dimPreview.centerMarks || []" :key="'cm' + ci" class="dim-center-mark" :transform="dimPreview.centerMarkAngle != null ? `translate(${cm.x}, ${cm.y}) rotate(${dimPreview.centerMarkAngle * 180 / Math.PI})` : `translate(${cm.x}, ${cm.y})`">
                  <line :x1="-cm.r" :y1="0" :x2="cm.r" :y2="0" />
                  <line :x1="0" :y1="-cm.r" :x2="0" :y2="cm.r" />
                </g>
                <template v-if="dimPreview.type === 'linear'">
                  <line :x1="dimPreview.ext1.x" :y1="dimPreview.ext1.y" :x2="dimPreview.ext1End.x" :y2="dimPreview.ext1End.y" class="dim-ext-line" />
                  <line :x1="dimPreview.ext2.x" :y1="dimPreview.ext2.y" :x2="dimPreview.ext2End.x" :y2="dimPreview.ext2End.y" class="dim-ext-line" />
                  <line :x1="dimPreview.dimLineStart.x" :y1="dimPreview.dimLineStart.y" :x2="dimPreview.dimLineEnd.x" :y2="dimPreview.dimLineEnd.y" class="dim-line" />
                  <polygon v-if="dimPreview.arrow1" :points="dimPreview.arrow1" class="dim-arrow" />
                  <polygon v-if="dimPreview.arrow2" :points="dimPreview.arrow2" class="dim-arrow" />
                  <text :x="dimPreview.textPos.x" :y="dimPreview.textPos.y" :transform="`rotate(${(dimPreview.textAngle || 0) * 180 / Math.PI}, ${dimPreview.textPos.x}, ${dimPreview.textPos.y})`" class="dim-text" text-anchor="middle" dominant-baseline="auto">{{ dimPreview.text }}</text>
                  <text v-if="dimPreview.labelText" :x="dimPreview.labelPos.x" :y="dimPreview.labelPos.y" :transform="`rotate(${(dimPreview.labelAngle || 0) * 180 / Math.PI}, ${dimPreview.labelPos.x}, ${dimPreview.labelPos.y})`" class="dim-text dim-label-text" text-anchor="end" dominant-baseline="auto">{{ dimPreview.labelText }}</text>
                </template>
              </template>
              <template v-if="dimPreview.type === 'diameter'">
                <template v-if="dimPreview.diameterMode === 'leader'">
                  <!-- 引线模式:水平文字线 + 折线引线 -->
                  <line :x1="dimPreview.textLineStart.x" :y1="dimPreview.textLineStart.y" :x2="dimPreview.textLineEnd.x" :y2="dimPreview.textLineEnd.y" class="dim-line" />
                  <line :x1="dimPreview.leaderBend.x" :y1="dimPreview.leaderBend.y" :x2="dimPreview.leaderEnd.x" :y2="dimPreview.leaderEnd.y" class="dim-line" />
                  <polygon v-if="dimPreview.arrow" :points="dimPreview.arrow" class="dim-arrow" />
                  <text :x="dimPreview.textPos.x" :y="dimPreview.textPos.y" class="dim-text" text-anchor="start" dominant-baseline="auto">{{ dimPreview.text }}</text>
                </template>
                <template v-else>
                  <!-- 直线模式:贯穿圆心 -->
                  <line :x1="dimPreview.leaderStart.x" :y1="dimPreview.leaderStart.y" :x2="dimPreview.leaderEnd.x" :y2="dimPreview.leaderEnd.y" class="dim-line" />
                  <polygon v-if="dimPreview.arrow" :points="dimPreview.arrow" class="dim-arrow" />
                  <text :x="dimPreview.textPos.x" :y="dimPreview.textPos.y" :transform="`rotate(${dimPreview.textAngle * 180 / Math.PI}, ${dimPreview.textPos.x}, ${dimPreview.textPos.y})`" class="dim-text" text-anchor="start" dominant-baseline="auto">{{ dimPreview.text }}</text>
                </template>
              </template>
              <template v-if="dimPreview.type === 'angle'">
                <path :d="dimPreview.arcPath" class="dim-line" fill="none" />
                <polygon v-if="dimPreview.arrow1" :points="dimPreview.arrow1" class="dim-arrow" />
                <polygon v-if="dimPreview.arrow2" :points="dimPreview.arrow2" class="dim-arrow" />
                <text :x="dimPreview.textPos.x" :y="dimPreview.textPos.y" class="dim-text" text-anchor="middle" dominant-baseline="auto">{{ dimPreview.text }}</text>
              </template>
            </g>

            <!-- 已放置标注 -->
            <g class="dimensions-layer">
              <g v-for="dim in renderedDimensions" :key="dim.id" :class="['dimension-group', { 'dimension-selected': selectedDimId === dim.id, 'dimension-hovered': dimHoveredId === String(dim.id) }]" :data-dim-id="dim.id" :style="{ '--dimension-color': dim.color }" @mousedown.stop="onDimMouseDown($event, dim)" @click.stop="onDimClick(dim)" @contextmenu.prevent.stop="openDimContextMenu($event, dim)">
                <!-- 线性标注 -->
                <template v-if="dim.type === 'linear'">
                  <g v-for="(cm, ci) in dim.centerMarks || []" :key="'cm' + ci" class="dim-center-mark" :transform="dim.centerMarkAngle != null ? `translate(${cm.x}, ${cm.y}) rotate(${dim.centerMarkAngle * 180 / Math.PI})` : `translate(${cm.x}, ${cm.y})`">
                    <line :x1="-cm.r" :y1="0" :x2="cm.r" :y2="0" />
                    <line :x1="0" :y1="-cm.r" :x2="0" :y2="cm.r" />
                  </g>
                  <line :x1="dim.ext1.x" :y1="dim.ext1.y" :x2="dim.ext1End.x" :y2="dim.ext1End.y" class="dim-ext-line" />
                  <line :x1="dim.ext1.x" :y1="dim.ext1.y" :x2="dim.ext1End.x" :y2="dim.ext1End.y" class="dim-hit-stroke" />
                  <line :x1="dim.ext2.x" :y1="dim.ext2.y" :x2="dim.ext2End.x" :y2="dim.ext2End.y" class="dim-ext-line" />
                  <line :x1="dim.ext2.x" :y1="dim.ext2.y" :x2="dim.ext2End.x" :y2="dim.ext2End.y" class="dim-hit-stroke" />
                  <line :x1="dim.dimLineStart.x" :y1="dim.dimLineStart.y" :x2="dim.dimLineEnd.x" :y2="dim.dimLineEnd.y" class="dim-line" />
                  <line :x1="dim.dimLineStart.x" :y1="dim.dimLineStart.y" :x2="dim.dimLineEnd.x" :y2="dim.dimLineEnd.y" class="dim-hit-stroke" />
                  <circle v-if="selectedDimId === dim.id" :cx="dim.dimLineStart.x" :cy="dim.dimLineStart.y" r="12" class="dim-extension-hit" :style="{ cursor: extensionCursor(dim) }" @mousedown.stop="onDimExtensionHandleDown($event, dim, 'start')" />
                  <circle v-if="selectedDimId === dim.id" :cx="dim.dimLineEnd.x" :cy="dim.dimLineEnd.y" r="12" class="dim-extension-hit" :style="{ cursor: extensionCursor(dim) }" @mousedown.stop="onDimExtensionHandleDown($event, dim, 'end')" />
                  <polygon v-if="dim.arrow1" :points="dim.arrow1" class="dim-arrow" />
                  <polygon v-if="dim.arrow2" :points="dim.arrow2" class="dim-arrow" />
                  <text :x="dim.textPos.x" :y="dim.textPos.y" :transform="`rotate(${(dim.textAngle || 0) * 180 / Math.PI}, ${dim.textPos.x}, ${dim.textPos.y})`" class="dim-text" style="cursor: move" text-anchor="middle" dominant-baseline="auto" @mousedown.stop="onDimTextMouseDown($event, dim)">{{ dim.text }}</text>
                  <text v-if="dim.labelText" :x="dim.labelPos.x" :y="dim.labelPos.y" :transform="`rotate(${(dim.labelAngle || 0) * 180 / Math.PI}, ${dim.labelPos.x}, ${dim.labelPos.y})`" class="dim-text dim-label-text" text-anchor="end" dominant-baseline="auto">{{ dim.labelText }}</text>
                </template>
                <!-- 直径标注 -->
                <template v-if="dim.type === 'diameter'">
                  <template v-if="dim.diameterMode === 'leader'">
                    <line :x1="dim.textLineStart.x" :y1="dim.textLineStart.y" :x2="dim.textLineEnd.x" :y2="dim.textLineEnd.y" class="dim-line" />
                    <line :x1="dim.textLineStart.x" :y1="dim.textLineStart.y" :x2="dim.textLineEnd.x" :y2="dim.textLineEnd.y" class="dim-hit-stroke" />
                    <line :x1="dim.leaderBend.x" :y1="dim.leaderBend.y" :x2="dim.leaderEnd.x" :y2="dim.leaderEnd.y" class="dim-line" />
                    <line :x1="dim.leaderBend.x" :y1="dim.leaderBend.y" :x2="dim.leaderEnd.x" :y2="dim.leaderEnd.y" class="dim-hit-stroke" />
                    <polygon v-if="dim.arrow" :points="dim.arrow" class="dim-arrow" />
                    <text :x="dim.textPos.x" :y="dim.textPos.y" class="dim-text" text-anchor="start" dominant-baseline="auto">{{ dim.text }}</text>
                  </template>
                  <template v-else>
                    <line :x1="dim.leaderStart.x" :y1="dim.leaderStart.y" :x2="dim.leaderEnd.x" :y2="dim.leaderEnd.y" class="dim-line" />
                    <line :x1="dim.leaderStart.x" :y1="dim.leaderStart.y" :x2="dim.leaderEnd.x" :y2="dim.leaderEnd.y" class="dim-hit-stroke" />
                    <polygon v-if="dim.arrow" :points="dim.arrow" class="dim-arrow" />
                    <text :x="dim.textPos.x" :y="dim.textPos.y" :transform="`rotate(${dim.textAngle * 180 / Math.PI}, ${dim.textPos.x}, ${dim.textPos.y})`" class="dim-text" text-anchor="start" dominant-baseline="auto">{{ dim.text }}</text>
                  </template>
                </template>
                <!-- 角度标注 -->
                <template v-if="dim.type === 'angle'">
                  <path :d="dim.arcPath" class="dim-line" fill="none" />
                  <path :d="dim.arcPath" class="dim-hit-stroke" fill="none" />
                  <polygon v-if="dim.arrow1" :points="dim.arrow1" class="dim-arrow" />
                  <polygon v-if="dim.arrow2" :points="dim.arrow2" class="dim-arrow" />
                  <text :x="dim.textPos.x" :y="dim.textPos.y" class="dim-text" text-anchor="middle" dominant-baseline="auto">{{ dim.text }}</text>
                </template>
                <!-- 孔位中心标记 -->
                <template v-if="dim.type === 'center-mark'">
                  <g v-for="(cm, ci) in dim.centerMarks || []" :key="'cm' + ci" class="dim-center-mark" :transform="`translate(${cm.x}, ${cm.y})`">
                    <line :x1="-cm.r" :y1="0" :x2="cm.r" :y2="0" />
                    <line :x1="0" :y1="-cm.r" :x2="0" :y2="cm.r" />
                    <line :x1="-cm.r" :y1="0" :x2="cm.r" :y2="0" class="dim-hit-stroke" />
                    <line :x1="0" :y1="-cm.r" :x2="0" :y2="cm.r" class="dim-hit-stroke" />
                  </g>
                </template>
              </g>
            </g>

            <g
              v-if="draggingFromPalette && draggingView && dragPreviewPos"
              :transform="`translate(${dragPreviewPos.x}, ${dragPreviewPos.y}) scale(${dragPreviewPos.scale})`"
              class="palette-drag-preview"
            >
              <rect
                :x="dragPreviewPos.bbox.x - 4"
                :y="dragPreviewPos.bbox.y - 4"
                :width="dragPreviewPos.bbox.width + 8"
                :height="dragPreviewPos.bbox.height + 8"
                fill="rgba(64, 158, 255, 0.06)"
                stroke="#409eff"
                stroke-width="2"
                stroke-dasharray="4,2"
                vector-effect="non-scaling-stroke"
              />
              <template v-for="(seg, i) in draggingView.edges || []" :key="`preview-${i}`">
                <line
                  v-if="seg && seg.type === 'line'"
                  :x1="seg.x1"
                  :y1="seg.y1"
                  :x2="seg.x2"
                  :y2="seg.y2"
                  stroke="#409eff"
                  stroke-width="1"
                  vector-effect="non-scaling-stroke"
                />
                <circle
                  v-else-if="seg && seg.type === 'circle'"
                  :cx="seg.cx"
                  :cy="seg.cy"
                  :r="seg.r"
                  fill="none"
                  stroke="#409eff"
                  stroke-width="1"
                  vector-effect="non-scaling-stroke"
                />
                <polyline
                  v-else-if="seg && seg.type === 'polyline'"
                  :points="polylinePoints(seg.points)"
                  fill="none"
                  stroke="#409eff"
                  stroke-width="1"
                  vector-effect="non-scaling-stroke"
                />
              </template>
            </g>
          </svg>

          <div v-if="showEmptyState" class="empty-state">
            <template v-if="!viewMode">
              <el-icon :size="48"><DocumentAdd /></el-icon>
              <p>选择型号并导入模型以开始</p>
              <p class="sub">导入后可从左侧拖拽视图到图纸</p>
            </template>
            <template v-else-if="viewLoading">
              <el-icon class="is-loading"><Loading /></el-icon>
              <p>正在加载工程图…</p>
            </template>
            <template v-else-if="viewError">
              <el-icon :size="48"><WarningFilled /></el-icon>
              <p>工程图加载失败</p>
              <p class="sub">{{ viewError }}</p>
            </template>
            <template v-else>
              <el-icon :size="48"><DocumentAdd /></el-icon>
              <p>暂无工程图内容</p>
            </template>
          </div>
        </div>
      </section>

      <aside v-if="!viewMode" class="property-panel">
        <div class="panel-header">属性面板</div>

        <section v-if="selectedView" class="property-section">
          <div class="section-title">视图属性</div>
          <div class="prop-row">
            <span class="prop-label">名称</span>
            <span class="prop-value">{{ selectedView.label }}</span>
          </div>
          <div class="prop-row">
            <span class="prop-label">边数</span>
            <span class="prop-value">{{ selectedView.edges?.length || 0 }}</span>
          </div>
          <div class="prop-row stacked">
            <span class="prop-label">全局比例</span>
            <el-input-number :model-value="selectedView.scale" :min="0.1" :max="5" :step="0.1" size="small" class="prop-input" @update:model-value="onViewScaleChange" />
          </div>
          <div class="prop-row">
            <span class="prop-label">位置</span>
            <span class="prop-value">{{ Math.round(selectedView.x) }}, {{ Math.round(selectedView.y) }}</span>
          </div>
          <el-button size="small" type="danger" plain class="full-button" @click="deleteSelectedView">
            <el-icon><Delete /></el-icon>
            删除此视图
          </el-button>
        </section>

        <section v-else class="property-section muted-section">
          <div class="section-title">当前选择</div>
          <p>未选择对象</p>
        </section>

        <section class="property-section">
          <div class="section-title">图纸统计</div>
          <div class="stat-row"><span>已放置视图</span><span class="num">{{ placedViews.length }}</span></div>
          <div class="stat-row"><span>图纸尺寸</span><span class="num">{{ sheetWidth }}×{{ sheetHeight }}</span></div>
          <div class="stat-row"><span>模型尺寸</span><span class="num">{{ modelBbox.width }}×{{ modelBbox.height }}×{{ modelBbox.depth }}mm</span></div>
        </section>

        <section class="property-section">
          <div class="section-title">标题栏 / BOM</div>
          <TitleBlockBomPanel
            :title-block-bom="titleBlockBom"
            :config="config"
            :model-params="modelParams"
          />
        </section>

        <section v-if="selectedDim" class="property-section">
          <div class="section-title">标注属性</div>
          <div class="prop-row">
            <span class="prop-label">类型</span>
            <span class="prop-value">{{ dimTypeLabel(selectedDim) }}</span>
          </div>
          <div v-if="selectedDim.type === 'linear' || selectedDim.type === 'diameter' || selectedDim.type === 'angle'" class="prop-row stacked">
            <span class="prop-label">自定义文字</span>
            <el-input
              :model-value="selectedDim.customText ?? ''"
              size="small"
              placeholder="留空显示测量值"
              clearable
              @update:model-value="v => setDimField(selectedDim.id, 'customText', v || null)"
            />
          </div>
          <div class="prop-row stacked">
            <span class="prop-label">伴随文字</span>
            <el-input
              :model-value="selectedDim.label ?? ''"
              size="small"
              placeholder='如"行程"、"总长"'
              clearable
              @update:model-value="v => setDimField(selectedDim.id, 'label', v || null)"
            />
            <span class="prop-hint">显示在数值左侧,前后端位置一致</span>
          </div>
          <div v-if="selectedDim.type === 'linear' && selectedDim.mode !== 'motor-envelope'" class="prop-row stacked">
            <span class="prop-label">绑定电机包络</span>
            <el-switch
              :model-value="!!selectedDim.bind_motor"
              @update:model-value="v => setDimField(selectedDim.id, 'bind_motor', v)"
            />
            <span class="prop-hint">换电机型号时两端自动跟随新包络</span>
          </div>
        </section>

        <section class="property-section document-json">
          <div class="section-title">工程图状态</div>
          <el-button
            size="small"
            type="primary"
            plain
            class="full-button"
            :loading="savingTemplate"
            :disabled="!selectedModel || !placedViews.length"
            @click="saveAsTemplate"
          >
            保存为模板
          </el-button>
          <el-button
            size="small"
            type="success"
            plain
            class="full-button"
            style="margin-left:0;margin-top:8px"
            @click="showTemplateDrawing = true"
          >
            <el-icon><Printer /></el-icon>
            模板出图(批量生成 PDF)
          </el-button>
          <pre>{{ drawingDocumentPreview }}</pre>
        </section>
      </aside>
    </main>

    <!-- 表格右键菜单:插入/删除行列、单元格对齐(抽离到 TableContextMenu) -->
    <TableContextMenu
      :menu="contextMenu"
      @insert-row="ctxInsertRow"
      @delete-row="ctxDeleteRow"
      @insert-col="ctxInsertCol"
      @delete-col="ctxDeleteCol"
      @set-align="setAlignOfSelected"
    />

    <!-- 标注右键菜单：切换箭头方向 -->
    <DimContextMenu
      :menu="dimContextMenu"
      @set-mode="setDimArrowMode"
    />

    <!-- 模板出图:导入模板 → 选同系列型号 → 批量生成 PDF → 下载 -->
    <TemplateDrawingPanel v-model="showTemplateDrawing" />
  </div>
</template>

<script setup>
// 组合根:只做各功能域的组合装配、事件总控与跨域编排。
// 依赖链单向:canvas → views → coords → viewDrag/dims;paletteDrag 依赖 coords+views。
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Upload, ZoomIn, ZoomOut, Delete, DocumentAdd, Loading, Printer, ArrowDown, Refresh, WarningFilled } from '@element-plus/icons-vue'
import { polylinePoints } from '@/dimensions/geometry.js'
import { useCanvasTransform } from '@/composables/useCanvasTransform'
import { useTouchCanvas } from '@/composables/useTouchCanvas'
import { useStyleConfig, TABLE_STYLE } from '@/composables/useStyleConfig'
import { useTablePresets } from '@/composables/useTablePresets'
import { usePlacedViews } from '@/composables/usePlacedViews'
import { useSheetCoords } from '@/composables/useSheetCoords'
import { useViewDrag } from '@/composables/useViewDrag'
import { useDimensions } from '@/composables/useDimensions'
import { useModelPalette } from '@/composables/useModelPalette'
import { usePaletteDrag } from '@/composables/usePaletteDrag'
import { useSymbolDrag } from '@/composables/useSymbolDrag'
import { usePlacedTables } from '@/composables/usePlacedTables'
import { useTableDrag } from '@/composables/useTableDrag'
import { useTableEdit } from '@/composables/useTableEdit'
import { partIndexAtPoint } from '@/tables/tableGeometry'
import { buildDrawingDocument, previewDocument } from '@/utils/drawingDocument'
import { exportSheetScreenshotPdf } from '@/utils/drawingPdf'
import { parseDrawingDocument, applyDrawingDocument } from '@/utils/loadDrawingDocument'
import { applySpec } from '@/utils/applySpec'
import { saveDrawingTemplate } from '@/api/drawingApi'
import TemplateDrawingPanel from '@/components/TemplateDrawingPanel.vue'
import TableLayer from '@/components/TableLayer.vue'
import TableSnapGuides from '@/components/TableSnapGuides.vue'
import TableContextMenu from '@/components/TableContextMenu.vue'
import DimContextMenu from '@/components/DimContextMenu.vue'
import TableSizePicker from '@/components/TableSizePicker.vue'
import TableStyleBar from '@/components/TableStyleBar.vue'
import SymbolPalette from '@/components/SymbolPalette.vue'
import TitleBlockBomPanel from '@/components/TitleBlockBomPanel.vue'
import { useTitleBlockBom } from '@/composables/useTitleBlockBom'

// ===== 只读展示模式(供小程序/外部系统通过 ?src=URL 直接打开源文件) =====
const urlParams = new URLSearchParams(window.location.search)
const viewMode = ref(urlParams.has('view') || urlParams.has('src'))
const viewSrc = ref(urlParams.get('src') || '')
const viewLoading = ref(false)
const viewError = ref('')
const viewerReady = ref(false)

async function loadViewSource(srcUrl) {
  if (!srcUrl) return
  viewLoading.value = true
  viewError.value = ''
  viewerReady.value = false
  try {
    const res = await fetch(srcUrl)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const raw = await res.text()
    const parsed = parseDrawingDocument(raw)
    // 规格回填:小程序以 ?spec=<JSON> 传入时,直接写进标题栏与参数表,跳过后端 render-drawing
    const specParam = urlParams.get('spec')
    if (specParam) {
      try {
        // decodeURIComponent 对纯 JSON(无 %) 为无操作,故同时兼容 uni 已解码/未解码两种传入
        const spec = JSON.parse(decodeURIComponent(specParam))
        applySpec(parsed, parsed.modelId || urlParams.get('modelId') || '', spec)
      } catch (se) {
        console.warn('[spec] 解析失败,跳过规格回填:', se)
      }
    }
    if (parsed.sheet && parsed.sheet.size) sheetSize.value = parsed.sheet.size
    if (parsed.modelId && models.value.includes(parsed.modelId)) selectedModel.value = parsed.modelId
    applyDrawingDocument(parsed, {
      placedViews: { setViews },
      dimensions: { setDimensions },
      placedTables: { setTables },
      titleBlockBom
    })
    if (parsed.droppedAnnotations) {
      ElMessage.warning(`已跳过 ${parsed.droppedAnnotations} 条标注(它引用的视图不在文件中)`)
    }
    viewerReady.value = true
    ElMessage.success('源文件已加载')
  } catch (e) {
    viewError.value = e.message
    ElMessage.error(`加载源文件失败: ${e.message}`)
  } finally {
    viewLoading.value = false
  }
}

// ===== 画布:图纸尺寸/整卡缩放平移 =====
const {
  sheetAreaRef, sheetSize, sheetWidth, sheetHeight, sheetZoom, sheetPan, sheetPanning, sheetCardStyle,
  setSheetSize, centerSheet, startSheetPan, updateSheetPan, endSheetPan, onSheetWheel
} = useCanvasTransform()

// 移动端查看浏览:单指平移 + 双指缩放(桌面端不接鼠标,无副作用)
useTouchCanvas({ areaRef: sheetAreaRef, sheetZoom, sheetPan })

// 注入前后端共享样式(标注字号/线宽等 CSS 变量)到 :root。
// 必须在此处调用:.dim-text 等字号取自这些变量,缺失时回退 9px(=9mm),
// 与图纸设定字号不符;导出内联样式也以 :root 上的值为准
useStyleConfig().applyToRoot()

const sheetSizeOptions = ['A4', 'A3', 'A2', 'A1', 'A0']
function onSheetSizeChange(name) {
  setSheetSize(name)
  // 视图与标注位置已固定在 sheet 像素坐标,切换尺寸后仍按当前坐标渲染,
  // 用户可手动调整视图放置位置
}

// ===== 已放置视图:放置/删除/全局比例 =====
const {
  placedViews, selectedViewId, globalScale, selectedView, placedViewNames,
  placeView, selectView, deleteSelectedView: removeSelectedView, clearViews, resetScale,
  setViews,
  onViewScaleChange, zoomCanvas, resetCanvas
} = usePlacedViews({ sheetWidth, sheetHeight })

// ===== 图纸坐标换算与边线引用 =====
const coords = useSheetCoords({ placedViews })
const { svgRef, getViewDisplayScale, viewSheetRect } = coords

// ===== 视图拖拽移动 + 投影对齐 =====
const { alignmentGuides, startMoveView, moveViewTo, endMoveView, clearGuides } =
  useViewDrag({ placedViews, selectedViewId, toSheetPoint: coords.eventToSheetPoint })

// ===== 型号选择与视图调色板数据 =====
// 需在标注引擎之前装配:getMotorEnvelope 依赖其 motorEnvelope
const {
  models, selectedModel, loadingViews, viewsLoaded, loadingText, error,
  lastElapsed, modelBbox, motorEnvelope, gearboxEnvelope, standardViews, isometricViews,
  config, modelParams,
  loadModelList, resetPalette, loadViewPalette
} = useModelPalette()

// ===== 标题栏 / BOM:绑定选型配置,支持手动覆盖 =====
const titleBlockBom = useTitleBlockBom()

// 配置就绪后为空白 BOM 自动建行;已有手工行则不动,避免覆盖用户编辑
watch([config, modelParams], ([cfg, mp]) => {
  if (cfg && titleBlockBom.bomTable.value.rows.length === 0) {
    titleBlockBom.rebuildBomFromConfig(cfg, mp)
  }
})

// ===== 标注:工具状态机与引擎装配 =====
const getMotorEnvelope = (view) => motorEnvelope.value[view.name]

const {
  activeTool, diameterSubMode, dimHoveredEdge, dimFirstEdge, dimPending, dimPreview, dimDragging,
  dimensionColor, dimensionColorPresets, dimensions, selectedDimId, renderedDimensions,
  dimHighlightEdges, dimHoveredId, selectedDim, setDimField,
  dimContextMenu, openDimContextMenu, closeDimContextMenu, setDimArrowMode,
  toggleTool, onDimEdgeSelect, onMotorEnvelopePick, onDimMouseDown, onDimTextMouseDown, onDimExtensionHandleDown, onDimDragMove, onGlobalDimMouseUp,
  onKeyDown, selectDim, onDimClick, onSvgMouseDown: onSvgMouseDownDim, onSvgMouseMove,
  onSvgMouseLeave, clearTransientSelection, removeByView, resetAll, setDimensions
} = useDimensions({ placedViews, selectedViewId, coords, getMotorEnvelope })

function closeAllContextMenus() {
  closeContextMenu()
  closeDimContextMenu()
}

// 预览模式(外部 ?src= 打开)下,编辑工具栏/调色板/属性面板已隐藏;
// 这里把空状态切到加载/错误文案并屏蔽画布编辑交互,保证只能看不能改。
const showEmptyState = computed(() =>
  viewMode.value
    ? !viewerReady.value && !viewLoading.value
    : !viewsLoaded.value && !loadingViews.value
)

// 需要命中圆的标注工具(其余工具下圆不参与命中)
const circleHitTools = ['diameter', 'linear', 'center-mark']

// ===== 调色板拖拽放置 =====
const {
  draggingFromPalette, draggingView, dragPreviewPos,
  onPalettePointerDown, onPalettePointerMove, onPalettePointerUp,
  resetPaletteDrag, dispose: disposePaletteDrag
} = usePaletteDrag({ coords, views: { placedViews, globalScale, placeView }, sheetWidth, sheetHeight })

// ===== 已放置表格:插入/拖拽/编辑/合并(抽离到 composable) =====
const tables = usePlacedTables()
const {
  placedTables, selectedTableId, selectedTable, selectedCells,
  placeTable, selectTable, deleteSelectedTable: removeSelectedTable, clearTables,
  setTables,
  updateCellText, setCellSymbol, clearCellSymbol, toggleCellSelect, mergeSelected, splitSelected, splitCell, findCellAt,
  insertRow, deleteRow, insertCol, deleteCol,
  resizeCol, resizeRow, resizeTable,
  setCellFontSize, setTableBorder
} = tables

// ===== 符号拖拽放置:从符号库拖 SVG 到单元格 =====
const {
  dragging: symbolDragging, draggingFile: symbolDraggingFile, previewPos: symbolPreviewPos,
  onSymbolPointerDown, onSymbolPointerMove, onSymbolPointerUp, reset: resetSymbolDrag
} = useSymbolDrag({ coords, placedTables, setCellSymbol })

// 拖拽 + 吸附(注入坐标转换与尺寸操作)
const {
  tableDrag, tableSnapGuides,
  startMove, startCornerResize, startColResize, startRowResize,
  move: moveTableDrag, end: endTableDrag
} = useTableDrag({
  placedTables, sheetWidth, sheetHeight,
  toSheetPoint: coords.eventToSheetPoint,
  resizeCol, resizeRow, resizeTable
})

// 编辑交互:inline 编辑 / 右键菜单 / 样式 / 键盘 / 插入
const {
  editingCell, hoverCell, contextMenu, activeFontSize, activeColor,
  startEdit, editCell, commitEdit, cancelEdit, onCellClick,
  startCellSelect, extendCellSelect, endCellSelect,
  onCellHover, clearHover,
  openContextMenu, closeContextMenu,
  ctxInsertRow, ctxDeleteRow, ctxInsertCol, ctxDeleteCol,
  setAlignOfSelected, setFontOfSelected, setColorOfSelected, setBorderWidth, setBorderColor,
  handleKeydown, insertEmptyTable, insertPresetTable
} = useTableEdit(tables, { sheetWidth, sheetHeight })

function onTableMouseDown(event, table) {
  if (activeTool.value) return
  selectTable(table.id)
  startMove(event, table)
}

// 单元格交互:单击进入编辑,拖拽则移动整张表(阈值区分,避免单击被误判为拖动)
const cellPointer = ref(null)
const DRAG_THRESHOLD = 4

/** 拆分单元格:把点击位置解析到具体子格。
 *  整格 cell.text 在拆分后不再显示,若落到整格会造成"输入了却看不到",故按坐标兜底。 */
function resolveEditPart(table, r, c, part, event) {
  if (part != null) return part
  const cell = findCellAt(table, r, c)
  if (!cell || !cell.split_dir || (cell.split_count || 0) < 2) return part
  const pt = coords.eventToSheetPoint(event)
  const idx = pt ? partIndexAtPoint(table, cell, pt) : -1
  return idx >= 0 ? idx : 0
}

function onCellMouseDown(event, table, r, c, part) {
  startCellSelect(event, table, r, c)   // Shift 走框选(内部已 stopPropagation)
  if (event.shiftKey) return
  // 非 Shift:拦截冒泡,避免触发表格整体拖动;先记录,移动超阈值才当作拖动
  event.stopPropagation()
  const p = resolveEditPart(table, r, c, part, event)
  cellPointer.value = { table, r, c, part: p, event, startX: event.clientX, startY: event.clientY, moved: false }
}

function onCellMouseEnter(event, table, r, c, part) {
  onCellHover(table, r, c, part)
}

// 双击单元格:若已含符号则清除,否则进入文字编辑
function onCellDblClick(event, table, r, c, part) {
  const cell = findCellAt(table, r, c)
  if (cell && cell.symbol) {
    clearCellSymbol(table.id, r, c)
    ElMessage.success('已清除单元格符号')
    return
  }
  startEdit(event, table, r, c, resolveEditPart(table, r, c, part, event))
}

// 字号控件显示用户最后设置的字号,切到别的单元格不再变回该单元格原字号
const selectedCellFontSize = computed(() => activeFontSize.value)
const selectedCellColor = computed(() => activeColor.value)

// 插入表格:尺寸选择器 → 空表格(Office 风格,无占位文字)
const showTablePicker = ref(false)
function onPickTableSize(rows, cols) {
  showTablePicker.value = false
  insertEmptyTable(rows, cols)
}

// 拆分单元格:在选中格内等分为 N 份(横向=左右,纵向=上下),不改动表格行列
const showSplitPicker = ref(false)
const splitDir = ref('h')
const splitCount = ref(2)
function applySplit() {
  const t = selectedTable.value
  const cells = selectedCells.value
  if (t && cells.length === 1) {
    splitCell(t.id, cells[0].r, cells[0].c, splitDir.value, splitCount.value)
  }
  showSplitPicker.value = false
}

// 表格模板:整套表格存后端,按原坐标灌回(幅面一致,坐标可直接复用)
const {
  presets: tablePresets, load: loadTablePresets,
  save: saveTablePreset, apply: applyTablePreset, remove: removeTablePreset
} = useTablePresets()

async function onSaveTablePreset() {
  let name
  try {
    ({ value: name } = await ElMessageBox.prompt(
      '保存当前图纸上的全部表格,之后可一键按原坐标放入', '存为表格模板', {
        inputPlaceholder: '模板名称',
        inputValidator: v => (v && v.trim()) ? true : '名称不能为空'
      }))
  } catch (e) {
    // 点取消时 ElMessageBox 以 'cancel' reject,不是异常
    if (e !== 'cancel') ElMessage.error(`保存失败:${e?.message || e}`)
    return
  }
  if (await saveTablePreset(name, placedTables.value)) {
    ElMessage.success(`已保存模板「${(name || '').trim()}」`)
  }
}

function onApplyTablePreset(id) {
  const n = applyTablePreset(id, placeTable)
  if (n > 0) ElMessage.success(`已放入 ${n} 张表格`)
}

async function onRemoveTablePreset(id) {
  if (await removeTablePreset(id)) ElMessage.success('已删除模板')
}

// 预览只给结构摘要:edges 全文可达几十万字符,直接塞进 <pre> 会拖垮编辑器
const drawingDocumentPreview = computed(
  () => JSON.stringify(previewDocument(buildDoc()), null, 2))

// ===== 模板保存:当前图纸(基准型号 + 视图布局 + 标注)落盘 =====

const savingTemplate = ref(false)
const showTemplateDrawing = ref(false)

const DIM_TYPE_LABELS = {
  linear: '线性标注',
  diameter: '直径标注',
  angle: '角度标注',
  'center-mark': '中心标记'
}

const LINEAR_MODE_LABELS = {
  single: '单边',
  parallel: '平行间距',
  center: '圆心距',
  'circle-edge': '圆心到边',
  'motor-envelope': '电机包络'
}

function dimTypeLabel(dim) {
  if (dim.type === 'linear' && dim.mode) {
    return `线性标注(${LINEAR_MODE_LABELS[dim.mode] || dim.mode})`
  }
  return DIM_TYPE_LABELS[dim.type] || dim.type
}

/** 根据尺寸线方向返回匹配的 resize 光标:水平/竖直/对角线 */
function extensionCursor(dim) {
  const a = dim.dimLineStart
  const b = dim.dimLineEnd
  if (!a || !b) return 'ew-resize'
  const dx = b.x - a.x
  const dy = b.y - a.y
  const absDx = Math.abs(dx)
  const absDy = Math.abs(dy)
  if (absDx > absDy * 2.4) return 'ew-resize'
  if (absDy > absDx * 2.4) return 'ns-resize'
  if ((dx > 0) === (dy > 0)) return 'nwse-resize'
  return 'nesw-resize'
}

function buildDoc() {
  return buildDrawingDocument({
    sheetSize: sheetSize.value,
    sheetWidth: sheetWidth.value,
    sheetHeight: sheetHeight.value,
    modelId: selectedModel.value,
    placedViews: placedViews.value,
    dimensions: dimensions.value,
    placedTables: placedTables.value,
    titleBlock: titleBlockBom.titleBlock.value,
    bomTable: titleBlockBom.bomTable.value
  })
}

async function exportDrawingDocument() {
  if (!selectedModel.value) { ElMessage.warning('请先选择并导入型号'); return }
  if (!placedViews.value.length) { ElMessage.warning('请先放置视图'); return }
  const doc = buildDoc()
  const blob = new Blob([JSON.stringify(doc, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${doc.model_id || 'drawing'}.json`
  a.click()
  URL.revokeObjectURL(url)
  ElMessage.success('源文件已导出到本地')
}

const exportingPdf = ref(false)

/** 所见即所得导出:直接把画布 SVG 光栅化进 PDF,不重画几何 */
async function exportPdf() {
  if (!placedViews.value.length) {
    ElMessage.warning('请先放置视图')
    return
  }
  exportingPdf.value = true
  try {
    // 清掉选中/悬浮/编辑态——这些是纯 UI 反馈,不应出现在图纸上
    selectedViewId.value = null
    selectedTableId.value = null
    selectedDimId.value = null
    selectedCells.value = []
    hoverCell.value = null
    editingCell.value = null
    await nextTick() // 等 DOM 同步清掉选中框后再克隆

    await exportSheetScreenshotPdf({
      svgEl: svgRef.value,
      sheetWidthMm: sheetWidth.value,
      sheetHeightMm: sheetHeight.value,
      fileName: `${selectedModel.value || 'drawing'}.pdf`,
      sheetZoom: sheetZoom.value
    })
    ElMessage.success('PDF 已导出')
  } catch (e) {
    ElMessage.error(`导出失败: ${e.message}`)
  } finally {
    exportingPdf.value = false
  }
}

const fileInputRef = ref(null)
function triggerImportDoc() {
  fileInputRef.value?.click()
}

// ===== output 目录源文件下拉 =====
const sourceOptions = ref([])
const selectedSource = ref('')
const loadingSources = ref(false)

async function loadSourceList() {
  loadingSources.value = true
  try {
    const res = await fetch('/api/drawing-sources')
    const data = await res.json()
    if (data.ok) {
      sourceOptions.value = data.sources || []
    }
  } catch (e) {
    // 后端未启动或不支持时静默:手动导入仍可用
  } finally {
    loadingSources.value = false
  }
}

async function onSourcePicked(name) {
  if (!name) return
  try {
    const res = await fetch(`/api/drawing-sources/${encodeURIComponent(name)}`)
    const data = await res.json()
    if (!data.ok) { ElMessage.error(data.error || '读取源文件失败'); return }
    applyDocRaw(data.raw, name)
  } catch (e) {
    ElMessage.error(`导入失败: ${e.message}`)
  } finally {
    selectedSource.value = ''
  }
}

/** 把一份源文件原文(字符串)解析并灌回画布,供文件导入与下拉导入复用 */
function applyDocRaw(raw, label) {
  try {
    const parsed = parseDrawingDocument(raw)
    if (parsed.sheet && parsed.sheet.size) sheetSize.value = parsed.sheet.size
    if (parsed.modelId && models.value.includes(parsed.modelId)) selectedModel.value = parsed.modelId
    applyDrawingDocument(parsed, {
      placedViews: { setViews },
      dimensions: { setDimensions },
      placedTables: { setTables },
      titleBlockBom
    })
    if (parsed.droppedAnnotations) {
      ElMessage.warning(`已跳过 ${parsed.droppedAnnotations} 条标注(它引用的视图不在文件中)`)
    }
    ElMessage.success(`源文件已载入${label ? `: ${label}` : ''},可继续编辑`)
  } catch (e) {
    ElMessage.error(`导入失败: ${e.message}`)
  }
}


async function onFilePicked(event) {
  const file = event.target.files && event.target.files[0]
  if (!file) return
  try {
    const text = await file.text()
    applyDocRaw(text, file.name)
  } catch (e) {
    ElMessage.error(`导入失败: ${e.message}`)
  } finally {
    event.target.value = ''
  }
}

async function saveAsTemplate() {
  if (!selectedModel.value) {
    ElMessage.warning('请先选择并导入型号')
    return
  }
  if (!placedViews.value.length) {
    ElMessage.warning('请先从调色板放置视图')
    return
  }
  const doc = buildDoc()
  savingTemplate.value = true
  try {
    const res = await saveDrawingTemplate(doc)
    if (res.ok) {
      ElMessage.success(`模板已保存: ${res.template_id}(系列 ${res.identity})`)
    } else {
      ElMessage.error(res.error || '保存失败')
    }
  } catch (e) {
    ElMessage.error(`保存失败: ${e.message}`)
  } finally {
    savingTemplate.value = false
  }
}

onMounted(async () => {
  await loadModelList()
  await loadTablePresets()
  await loadSourceList()
  centerSheet()
  const initModel = urlParams.get('model')
  if (initModel && models.value.includes(initModel)) {
    selectedModel.value = initModel
    await loadViewPalette()
  } else if (viewMode.value && viewSrc.value) {
    await loadViewSource(viewSrc.value)
  }
  window.addEventListener('mousemove', onGlobalMouseMove)
  window.addEventListener('mouseup', onGlobalMouseUp)
  window.addEventListener('pointermove', onPalettePointerMove)
  window.addEventListener('pointerup', onPalettePointerUp)
  window.addEventListener('pointercancel', resetPaletteDrag)
  window.addEventListener('pointermove', onSymbolPointerMove)
  window.addEventListener('pointerup', onSymbolPointerUp)
  window.addEventListener('pointercancel', resetSymbolDrag)
  window.addEventListener('keydown', onKeyDown)
  window.addEventListener('keydown', handleKeydown)
  window.addEventListener('click', closeAllContextMenus)
})

onUnmounted(() => {
  window.removeEventListener('mousemove', onGlobalMouseMove)
  window.removeEventListener('mouseup', onGlobalMouseUp)
  window.removeEventListener('pointermove', onPalettePointerMove)
  window.removeEventListener('pointerup', onPalettePointerUp)
  window.removeEventListener('pointercancel', resetPaletteDrag)
  window.removeEventListener('pointermove', onSymbolPointerMove)
  window.removeEventListener('pointerup', onSymbolPointerUp)
  window.removeEventListener('pointercancel', resetSymbolDrag)
  window.removeEventListener('keydown', onKeyDown)
  window.removeEventListener('keydown', handleKeydown)
  window.removeEventListener('click', closeAllContextMenus)
  disposePaletteDrag()
})

// ===== 事件总控(跨画布/视图/标注多域,保留在组件内编排) =====

function onSvgMouseDown(event) {
  // 中键:整卡平移
  if (event.button === 1) {
    event.preventDefault()
    startSheetPan(event)
    return
  }
  // 标注工具激活:交给标注引擎处理边线选择/放置/取消
  if (activeTool.value) {
    onSvgMouseDownDim(event)
    return
  }
  // 普通模式:点击空白处取消选中(视图/标注/表格)
  if (event.target.tagName === 'rect' || event.target.tagName === 'svg') {
    selectedViewId.value = null
    selectedDimId.value = null
    selectedTableId.value = null
    selectedCells.value = []
  }
}

function onViewMouseDown(event, view) {
  // 标注工具激活时禁止拖动视图
  if (activeTool.value) return
  startMoveView(event, view)
}

function onGlobalMouseMove(event) {
  if (sheetPanning.value) {
    updateSheetPan(event)
    return
  }
  if (dimDragging.value) {
    onDimDragMove(event)
    return
  }
  // 单元格上按下后若移动超阈值,转成整表拖动
  if (cellPointer.value && !cellPointer.value.moved) {
    const dx = event.clientX - cellPointer.value.startX
    const dy = event.clientY - cellPointer.value.startY
    if (Math.hypot(dx, dy) > DRAG_THRESHOLD) {
      cellPointer.value.moved = true
      startMove(cellPointer.value.event, cellPointer.value.table)
    }
  }
  moveViewTo(event)
  moveTableDrag(event)
}

function onGlobalMouseUp() {
  endSheetPan()
  endMoveView()
  endTableDrag()
  endCellSelect()
  onGlobalDimMouseUp()
  // 单元格仅点击(未拖动):进入编辑(part 有值时编辑对应拆分子格)
  if (cellPointer.value && !cellPointer.value.moved) {
    const { table, r, c, part } = cellPointer.value
    editCell(table, r, c, part)
  }
  cellPointer.value = null
}

/** dim-hit-layer 内已放置标注命中副本的事件转发。
 * 副本位于命中层最顶层,事件冒泡到外层 g,这里反查 data-dim-id 找到 dim。 */
function resolveDimFromEvent(event) {
  const el = event.target?.closest?.('[data-dim-id]')
  if (!el) return null
  return dimensions.value.find(d => String(d.id) === el.dataset.dimId) || null
}

function onDimHitMouseDown(event) {
  const dim = resolveDimFromEvent(event)
  if (!dim) return
  onDimMouseDown(event, dim)
}

function onDimHitClick(event) {
  const dim = resolveDimFromEvent(event)
  if (!dim) return
  onDimClick(dim)
}

// ===== 跨域编排 =====

/** 删除选中视图,并同步清理引用它的标注 */
function deleteSelectedView() {
  const removedId = removeSelectedView()
  if (removedId) {
    removeByView(removedId)
    clearTransientSelection()
  }
}

/** 工具栏清空:视图 + 标注 + 全局比例 + 对齐线 + 表格 */
function clearPlacedViews() {
  clearViews()
  resetScale()
  clearGuides()
  resetAll()
  clearTables()
}

/** 切换型号:重置调色板并清空已放置视图 */
function onModelChange() {
  resetPalette()
  clearViews()
}
</script>

<style scoped>
.sw-drawing-app {
  display: flex;
  flex-direction: column;
  height: calc(100vh - var(--panel-nav-offset, 60px));
  overflow: hidden;
  background: #f0f2f5;
}

.top-toolbar {
  display: flex;
  align-items: center;
  align-content: center;
  justify-content: space-between;
  flex-wrap: wrap;
  row-gap: 6px;
  min-height: 48px;
  padding: 8px 14px;
  background: #fff;
  border-bottom: 1px solid #dcdfe6;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.04);
  flex-shrink: 0;
}

.toolbar-left,
.toolbar-center,
.toolbar-right {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  min-width: 0;
}

.toolbar-center {
  flex: 1;
  justify-content: center;
}

.toolbar-right {
  justify-content: flex-end;
  min-width: 180px;
}

.app-title {
  font-weight: 600;
  font-size: 15px;
  color: #303133;
  white-space: nowrap;
}

.model-select {
  width: 220px;
}

.status-text { color: #409eff; font-size: 12px; }
.status-ok { color: #67c23a; font-size: 12px; }
.status-err { color: #f56c6c; font-size: 12px; }

.editor-shell {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr) 280px;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.editor-shell.view-mode {
  grid-template-columns: minmax(0, 1fr);
}

/* 预览模式:屏蔽画布上的视图/表格/标注编辑交互,只能看不能改;
   缩放与平移由 svg 根节点的 wheel/中键事件处理,不受影响 */
.editor-shell.view-mode .placed-view,
.editor-shell.view-mode .placed-table,
.editor-shell.view-mode .dimensions-layer,
.editor-shell.view-mode .dim-hit-dims {
  pointer-events: none;
}

.view-palette,
.property-panel {
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow-y: auto;
  background: #fff;
}

.view-palette {
  border-right: 1px solid #dcdfe6;
}

.property-panel {
  border-left: 1px solid #dcdfe6;
}

.panel-header {
  padding: 12px 16px;
  font-weight: 600;
  font-size: 14px;
  color: #303133;
  border-bottom: 1px solid #ebeef5;
  background: #fafafa;
  flex-shrink: 0;
}

.panel-empty {
  padding: 40px 16px;
  text-align: center;
  color: #909399;
}

.panel-empty .sub,
.empty-state .sub {
  font-size: 12px;
  color: #c0c4cc;
  margin-top: 6px;
}

.palette-section,
.property-section {
  padding: 12px;
  border-bottom: 1px solid #f0f2f5;
}

.section-title {
  font-size: 12px;
  font-weight: 600;
  color: #606266;
  margin-bottom: 8px;
  text-transform: uppercase;
}

.view-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.view-item {
  cursor: grab;
  touch-action: none;
  user-select: none;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  padding: 4px;
  text-align: center;
  transition: all 0.15s;
  background: #fff;
}

.view-item:hover {
  border-color: #409eff;
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.15);
  transform: translateY(-1px);
}

.view-item:active {
  cursor: grabbing;
}

.view-item.is-placed {
  opacity: 0.35;
  cursor: not-allowed;
  pointer-events: none;
  border-color: #dcdfe6;
  background: #f5f7fa;
}

.view-item.is-placed .view-label {
  color: #c0c4cc;
}

.view-thumbnail {
  width: 100%;
  height: 70px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #fafafa;
  border-radius: 2px;
  overflow: hidden;
}

.view-thumbnail :deep(svg) {
  max-width: 100%;
  max-height: 100%;
}

.view-label {
  display: block;
  font-size: 11px;
  color: #606266;
  margin-top: 3px;
}

.canvas-region {
  min-width: 0;
  min-height: 0;
  background: #e8eaed;
  overflow: hidden;
}

.sheet-area {
  width: 100%;
  height: 100%;
  position: relative;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
}

.sheet-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(0, 0, 0, 0.04) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0, 0, 0, 0.04) 1px, transparent 1px);
  background-size: 20px 20px;
  pointer-events: none;
}

.drawing-sheet {
  position: absolute;
  transform-origin: 0 0;
  cursor: default;
  z-index: 1;
  background: #fff;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.15);
  flex-shrink: 0;
  user-select: none;
  -webkit-user-select: none;
  touch-action: none;
}

.placed-view {
  cursor: move;
}

::global(body.sheet-panning),
::global(body.sheet-panning *) {
  cursor: grabbing !important;
}

.placed-view.selected {
  filter: drop-shadow(0 0 4px rgba(64, 158, 255, 0.3));
}

.palette-drag-preview {
  pointer-events: none;
  opacity: 0.58;
}

.empty-state {
  position: absolute;
  z-index: 2;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  text-align: center;
  color: #909399;
  pointer-events: none;
}

.prop-row,
.stat-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  padding: 5px 0;
  font-size: 12px;
  color: #606266;
}

.prop-row.stacked {
  align-items: flex-start;
  flex-direction: column;
}

.prop-label {
  color: #909399;
}

.prop-hint {
  color: #909399;
  font-size: 11px;
  margin-left: 8px;
}

.prop-value,
.stat-row .num {
  color: #303133;
  font-weight: 500;
  text-align: right;
}

.prop-input,
.full-button {
  width: 100%;
}

.full-button {
  margin-top: 8px;
}

.muted-section {
  color: #909399;
  font-size: 12px;
}

.document-json pre {
  max-height: 260px;
  overflow: auto;
  padding: 8px;
  border-radius: 4px;
  background: #f6f8fa;
  color: #303133;
  font-size: 11px;
  line-height: 1.45;
  white-space: pre-wrap;
  word-break: break-word;
}

/* ===== 表格预设下拉:名称与删除图标分列两端 ===== */
.preset-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
}
.preset-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.preset-del {
  flex-shrink: 0;
  color: #c0c4cc;
}
.preset-del:hover {
  color: #f56c6c;
}

/* ===== 拆分单元格弹窗:方向选择 + 份数 ===== */
.split-picker {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.split-count-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-size: 13px;
  color: #606266;
}
.split-apply {
  width: 100%;
}

/* ===== 标注工具样式 ===== */
.dim-hit-line,
.dim-hit-circle {
  stroke: transparent;
  stroke-width: 10;
  fill: none;
  cursor: crosshair;
}

.dim-hit-circle {
  fill: none;
}

.dim-highlight-hover {
  stroke: #409eff;
  stroke-width: 3;
  fill: none;
  vector-effect: non-scaling-stroke;
}

/* 视图边线(与后端共用 cad_viewer_style.json 配置) */
.visible-edges line,
.visible-edges polyline,
.visible-edges circle {
  stroke: #333;
  stroke-width: var(--edge-visible-stroke, 1);
  vector-effect: non-scaling-stroke;
}
.hidden-edges line,
.hidden-edges polyline,
.hidden-edges circle {
  stroke: #999;
  stroke-width: var(--edge-hidden-stroke, 0.8);
  stroke-dasharray: 3 2;
  vector-effect: non-scaling-stroke;
}

.dim-highlight-selected {
  stroke: #67c23a;
  stroke-width: 3;
  fill: none;
  vector-effect: non-scaling-stroke;
}

.dim-ext-line {
  stroke: var(--dimension-color, #606266);
  stroke-width: var(--dim-ext-stroke, 0.8);
  vector-effect: non-scaling-stroke;
}

.dim-line {
  stroke: var(--dimension-color, #303133);
  stroke-width: var(--dim-line-stroke, 1);
  vector-effect: non-scaling-stroke;
}

.dim-arrow {
  fill: var(--dimension-color, #303133);
  vector-effect: non-scaling-stroke;
}

/* 待固定预览：虚线表示还没落位，再点一次左键才确定 */
.dim-preview-pending .dim-line,
.dim-preview-pending .dim-ext-line {
  stroke-dasharray: 5 3;
}

/* 中心标记：实线十字。排除命中加宽的透明副本，
   否则 .dim-center-mark line 优先级更高会把副本染成可见粗线 */
.dim-center-mark line:not(.dim-hit-stroke) {
  stroke: var(--dimension-color, #303133);
  stroke-width: var(--center-mark-stroke, 0.8);
  vector-effect: non-scaling-stroke;
}

.dim-text {
  font-size: var(--dim-text-size, 9px);
  fill: var(--dimension-color, #303133);
  font-family: 'Microsoft YaHei', sans-serif;
  user-select: none;
  -webkit-user-select: none;
}

/* 伴随文字标签：与数值同字号,右对齐(末端紧贴间距) */
.dim-label-text {
  text-anchor: end;
}

.dimension-group {
  cursor: pointer;
  pointer-events: all;
}

/* 命中加宽的透明副本:不影响视觉,只把命中区从 1px 扩到 ~12px。
   标注工具激活时整层让路:由 dim-hit-layer 内的"已放置标注副本"统一接管命中,
   避免 12px 命中带与模型边线/其他标注互相遮挡。 */
.dim-hit-stroke {
  fill: none;
  stroke: transparent;
  stroke-width: 12;
  pointer-events: all;
  vector-effect: non-scaling-stroke;
}

.drawing-sheet.dim-active .dim-hit-stroke {
  pointer-events: none;
}

/* 箭头 fill 命中(父 group 已 visiblePainted,显式声明更稳) */
.dim-arrow {
  pointer-events: visiblePainted;
}

.dimension-selected .dim-line {
  stroke-width: 1.5;
}

.dimension-selected .dim-text {
  font-weight: 600;
}

/* 悬浮高亮:已放置标注的命中带比可见线宽很多,必须有可见反馈,
   否则用户无从判断鼠标是否已在尺寸线上(标注工具激活时尤其重要)。
   放在 .dimension-selected 之后,hover 态优先显示。
   :not(.dim-hit-stroke) 排除加宽的透明副本,否则会被染成可见粗线。 */
.dimension-hovered .dim-line,
.dimension-hovered .dim-ext-line,
.dimension-hovered .dim-center-mark line:not(.dim-hit-stroke) {
  stroke: #409eff;
  stroke-width: 2;
}

.dimension-hovered .dim-arrow {
  fill: #409eff;
}

.dimension-hovered .dim-text {
  fill: #409eff;
  font-weight: 600;
}

/* 选中线性标注时,尺寸线两端出现透明拖拽热区(圆形,覆盖箭尾位置)。
   光标由 inline style 动态设置,匹配尺寸线方向。 */
.dim-extension-hit {
  fill: transparent;
  stroke: none;
  pointer-events: all;
}

.drawing-sheet.dim-active {
  cursor: crosshair;
}

@media (max-width: 1080px) {
  .editor-shell {
    grid-template-columns: 220px minmax(0, 1fr) 240px;
  }

  .model-select {
    width: 180px;
  }
}

/* 移动端查看浏览:隐藏编辑工具、侧栏与状态栏,画布占满,开启触控手势 */
@media (max-width: 1024px) {
  .mobile-hide {
    display: none;
  }

  .top-toolbar {
    flex-wrap: wrap;
    row-gap: 6px;
  }

  .app-title {
    display: none;
  }

  .editor-shell {
    grid-template-columns: 1fr;
  }

  .view-palette,
  .property-panel {
    display: none;
  }

  .sheet-area {
    touch-action: none;
    padding: 12px;
  }

  .model-select {
    width: 150px;
  }
}

</style>
