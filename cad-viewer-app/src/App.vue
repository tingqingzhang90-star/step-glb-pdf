<template>
  <div class="sw-drawing-app">
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
        <el-divider direction="vertical" />
        <el-button-group>
          <el-button size="small" :type="activeTool === 'linear' ? 'primary' : ''" :disabled="!viewsLoaded" @click="toggleTool('linear')">线性</el-button>
          <el-button size="small" :type="activeTool === 'diameter' ? 'primary' : ''" :disabled="!viewsLoaded" @click="toggleTool('diameter')">直径</el-button>
          <el-button size="small" :type="activeTool === 'angle' ? 'primary' : ''" :disabled="!viewsLoaded" @click="toggleTool('angle')">角度</el-button>
          <el-button size="small" :type="activeTool === 'center-mark' ? 'primary' : ''" :disabled="!viewsLoaded" @click="toggleTool('center-mark')">中心</el-button>
        </el-button-group>
        <el-color-picker v-model="dimensionColor" size="small" :predefine="dimensionColorPresets" aria-label="标注颜色" />
        <el-divider direction="vertical" />
        <el-button size="small" :icon="Delete" :disabled="placedViews.length === 0" @click="clearPlacedViews">清空</el-button>
      </div>

      <div class="toolbar-right">
        <span v-if="loadingText" class="status-text">{{ loadingText }}</span>
        <span v-if="lastElapsed" class="status-ok">耗时 {{ lastElapsed }}s</span>
        <span v-if="error" class="status-err">{{ error }}</span>
      </div>
    </header>

    <main class="editor-shell">
      <aside class="view-palette">
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

            <!-- 标注命中层（仅标注工具激活时） -->
            <g v-if="activeTool" class="dim-hit-layer" pointer-events="stroke">
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
                    <line :x1="dim.dimStart.x" :y1="dim.dimStart.y" :x2="dim.dimEnd.x" :y2="dim.dimEnd.y" class="dim-hit-line" :data-dim-id="dim.id" />
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
                    <line :x1="dim.dimStart.x" :y1="dim.dimStart.y" :x2="dim.dimEnd.x" :y2="dim.dimEnd.y" class="dim-hit-line" :data-dim-id="dim.id" />
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
                  <line :x1="dimPreview.dimStart.x" :y1="dimPreview.dimStart.y" :x2="dimPreview.dimEnd.x" :y2="dimPreview.dimEnd.y" class="dim-line" />
                  <polygon v-if="dimPreview.arrow1" :points="dimPreview.arrow1" class="dim-arrow" />
                  <polygon v-if="dimPreview.arrow2" :points="dimPreview.arrow2" class="dim-arrow" />
                  <text :x="dimPreview.textPos.x" :y="dimPreview.textPos.y" class="dim-text" text-anchor="middle" dominant-baseline="auto">{{ dimPreview.text }}</text>
                </template>
              </template>
              <template v-if="dimPreview.type === 'diameter'">
                <line :x1="dimPreview.leaderStart.x" :y1="dimPreview.leaderStart.y" :x2="dimPreview.leaderEnd.x" :y2="dimPreview.leaderEnd.y" class="dim-line" />
                <polygon v-if="dimPreview.arrow" :points="dimPreview.arrow" class="dim-arrow" />
                <text :x="dimPreview.textPos.x" :y="dimPreview.textPos.y" :transform="`rotate(${dimPreview.textAngle * 180 / Math.PI}, ${dimPreview.textPos.x}, ${dimPreview.textPos.y})`" class="dim-text" text-anchor="start" dominant-baseline="auto">{{ dimPreview.text }}</text>
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
              <g v-for="dim in renderedDimensions" :key="dim.id" :class="['dimension-group', { 'dimension-selected': selectedDimId === dim.id, 'dimension-hovered': dimHoveredId === String(dim.id) }]" :data-dim-id="dim.id" :style="{ '--dimension-color': dim.color }" @mousedown.stop="onDimMouseDown($event, dim)" @click.stop="onDimClick(dim)">
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
                  <line :x1="dim.dimStart.x" :y1="dim.dimStart.y" :x2="dim.dimEnd.x" :y2="dim.dimEnd.y" class="dim-line" />
                  <line :x1="dim.dimStart.x" :y1="dim.dimStart.y" :x2="dim.dimEnd.x" :y2="dim.dimEnd.y" class="dim-hit-stroke" />
                  <polygon v-if="dim.arrow1" :points="dim.arrow1" class="dim-arrow" />
                  <polygon v-if="dim.arrow2" :points="dim.arrow2" class="dim-arrow" />
                  <text :x="dim.textPos.x" :y="dim.textPos.y" class="dim-text" text-anchor="middle" dominant-baseline="auto">{{ dim.text }}</text>
                </template>
                <!-- 直径标注 -->
                <template v-if="dim.type === 'diameter'">
                  <line :x1="dim.leaderStart.x" :y1="dim.leaderStart.y" :x2="dim.leaderEnd.x" :y2="dim.leaderEnd.y" class="dim-line" />
                  <line :x1="dim.leaderStart.x" :y1="dim.leaderStart.y" :x2="dim.leaderEnd.x" :y2="dim.leaderEnd.y" class="dim-hit-stroke" />
                  <polygon v-if="dim.arrow" :points="dim.arrow" class="dim-arrow" />
                  <text :x="dim.textPos.x" :y="dim.textPos.y" :transform="`rotate(${dim.textAngle * 180 / Math.PI}, ${dim.textPos.x}, ${dim.textPos.y})`" class="dim-text" text-anchor="start" dominant-baseline="auto">{{ dim.text }}</text>
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

          <div v-if="!viewsLoaded && !loadingViews" class="empty-state">
            <el-icon :size="48"><DocumentAdd /></el-icon>
            <p>选择型号并导入模型以开始</p>
            <p class="sub">导入后可从左侧拖拽视图到图纸</p>
          </div>
        </div>
      </section>

      <aside class="property-panel">
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
          <div v-if="selectedDim.type === 'linear'" class="prop-row stacked">
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

    <!-- 模板出图:导入模板 → 选同系列型号 → 批量生成 PDF → 下载 -->
    <TemplateDrawingPanel v-model="showTemplateDrawing" />
  </div>
</template>

<script setup>
// 组合根:只做各功能域的组合装配、事件总控与跨域编排。
// 依赖链单向:canvas → views → coords → viewDrag/dims;paletteDrag 依赖 coords+views。
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Upload, ZoomIn, ZoomOut, Delete, DocumentAdd, Loading, Printer } from '@element-plus/icons-vue'
import { polylinePoints } from '@/dimensions/geometry.js'
import { useCanvasTransform } from '@/composables/useCanvasTransform'
import { usePlacedViews } from '@/composables/usePlacedViews'
import { useSheetCoords } from '@/composables/useSheetCoords'
import { useViewDrag } from '@/composables/useViewDrag'
import { useDimensions } from '@/composables/useDimensions'
import { useModelPalette } from '@/composables/useModelPalette'
import { usePaletteDrag } from '@/composables/usePaletteDrag'
import { buildDrawingDocument } from '@/utils/drawingDocument'
import { saveDrawingTemplate } from '@/api/drawingApi'
import TemplateDrawingPanel from '@/components/TemplateDrawingPanel.vue'

// ===== 画布:图纸尺寸/整卡缩放平移 =====
const {
  sheetAreaRef, sheetSize, sheetWidth, sheetHeight, sheetZoom, sheetPanning, sheetCardStyle,
  setSheetSize, centerSheet, startSheetPan, updateSheetPan, endSheetPan, onSheetWheel
} = useCanvasTransform()

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
  onViewScaleChange, zoomCanvas, resetCanvas
} = usePlacedViews({ sheetWidth, sheetHeight })

// ===== 图纸坐标换算与边线引用 =====
const coords = useSheetCoords({ placedViews })
const { svgRef, getViewDisplayScale } = coords

// ===== 视图拖拽移动 + 投影对齐 =====
const { alignmentGuides, startMoveView, moveViewTo, endMoveView, clearGuides } =
  useViewDrag({ placedViews, selectedViewId, toSheetPoint: coords.eventToSheetPoint })

// ===== 标注:工具状态机与引擎装配 =====
const {
  activeTool, dimHoveredEdge, dimPending, dimPreview, dimDragging,
  dimensionColor, dimensionColorPresets, dimensions, selectedDimId, renderedDimensions,
  dimHighlightEdges, dimHoveredId, selectedDim, setDimField,
  toggleTool, onDimEdgeSelect, onDimMouseDown, onDimDragMove, onGlobalDimMouseUp,
  onKeyDown, selectDim, onDimClick, onSvgMouseDown: onSvgMouseDownDim, onSvgMouseMove,
  onSvgMouseLeave, clearTransientSelection, removeByView, resetAll
} = useDimensions({ placedViews, selectedViewId, coords })

// 需要命中圆的标注工具(其余工具下圆不参与命中)
const circleHitTools = ['diameter', 'linear', 'center-mark']

// ===== 型号选择与视图调色板数据 =====
const {
  models, selectedModel, loadingViews, viewsLoaded, loadingText, error,
  lastElapsed, modelBbox, standardViews, isometricViews,
  loadModelList, resetPalette, loadViewPalette
} = useModelPalette()

// ===== 调色板拖拽放置 =====
const {
  draggingFromPalette, draggingView, dragPreviewPos,
  onPalettePointerDown, onPalettePointerMove, onPalettePointerUp,
  resetPaletteDrag, dispose: disposePaletteDrag
} = usePaletteDrag({ coords, views: { placedViews, globalScale, placeView }, sheetWidth, sheetHeight })

const drawingDocumentPreview = computed(() => JSON.stringify(
  buildDrawingDocument({
    sheetSize: sheetSize.value,
    sheetWidth: sheetWidth.value,
    sheetHeight: sheetHeight.value,
    modelId: selectedModel.value,
    placedViews: placedViews.value,
    dimensions: dimensions.value
  }),
  null, 2
))

// ===== 模板保存:当前图纸(基准型号 + 视图布局 + 标注)落盘 =====

const savingTemplate = ref(false)
const showTemplateDrawing = ref(false)

const DIM_TYPE_LABELS = {
  linear: '线性标注',
  diameter: '直径标注',
  angle: '角度标注',
  'center-mark': '中心标记'
}

function dimTypeLabel(dim) {
  if (dim.type === 'linear' && dim.mode) {
    const modeLabels = { single: '单边', parallel: '平行间距', center: '圆心距', 'circle-edge': '圆心到边' }
    return `线性标注(${modeLabels[dim.mode] || dim.mode})`
  }
  return DIM_TYPE_LABELS[dim.type] || dim.type
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
  const doc = buildDrawingDocument({
    sheetSize: sheetSize.value,
    sheetWidth: sheetWidth.value,
    sheetHeight: sheetHeight.value,
    modelId: selectedModel.value,
    placedViews: placedViews.value,
    dimensions: dimensions.value
  })
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
  centerSheet()
  window.addEventListener('mousemove', onGlobalMouseMove)
  window.addEventListener('mouseup', onGlobalMouseUp)
  window.addEventListener('pointermove', onPalettePointerMove)
  window.addEventListener('pointerup', onPalettePointerUp)
  window.addEventListener('pointercancel', resetPaletteDrag)
  window.addEventListener('keydown', onKeyDown)
})

onUnmounted(() => {
  window.removeEventListener('mousemove', onGlobalMouseMove)
  window.removeEventListener('mouseup', onGlobalMouseUp)
  window.removeEventListener('pointermove', onPalettePointerMove)
  window.removeEventListener('pointerup', onPalettePointerUp)
  window.removeEventListener('pointercancel', resetPaletteDrag)
  window.removeEventListener('keydown', onKeyDown)
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
  // 普通模式:点击空白处取消选中
  if (event.target.tagName === 'rect' || event.target.tagName === 'svg') {
    selectedViewId.value = null
    selectedDimId.value = null
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
  moveViewTo(event)
}

function onGlobalMouseUp() {
  endSheetPan()
  endMoveView()
  onGlobalDimMouseUp()
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

/** 工具栏清空:视图 + 标注 + 全局比例 + 对齐线 */
function clearPlacedViews() {
  clearViews()
  resetScale()
  clearGuides()
  resetAll()
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
  height: 100vh;
  overflow: hidden;
  background: #f0f2f5;
}

.top-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
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
</style>
