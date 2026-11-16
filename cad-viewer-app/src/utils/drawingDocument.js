// 工程图源文件(JSON)序列化,纯函数。
// 同系列投影视图几何(矢量边)固化进文件,解析时免重投影;型号切换只刷新
// 表格数据 + 重算标注值(见 docs/同系列模板复用规则.md)。
// px_per_mm: 调色板归一化比例(画布 px / 模型 mm),后端重算视图物理比例用
// customText: 用户自定义标注文字(如"减速机尺寸"),留空则显示测量值
// bind_motor: 线性标注绑定电机包络锚点,换电机时两端自动跟随新包络

export const SCHEMA_VERSION = '1.0'

export function buildDrawingDocument({ sheetSize, sheetWidth, sheetHeight, modelId, placedViews, dimensions, placedTables, titleBlock, bomTable }) {
  const doc = {
    schema_version: SCHEMA_VERSION,
    sheet: {
      size: sheetSize || 'A3',
      width: sheetWidth,
      height: sheetHeight
    },
    model_id: modelId || null,
    views: placedViews.map(v => ({
      id: v.id,
      source_view: v.name,
      label: v.label,
      group: v.group,
      x: Math.round(v.x),
      y: Math.round(v.y),
      scale: Number(v.scale.toFixed(2)),
      px_per_mm: v.bbox?.scale ?? null,
      // 视图投影几何自包含:解析时直接还原渲染,无需后端重新投影
      bbox: v.bbox,
      contentBBox: v.contentBBox,
      edges: v.edges,
      hidden_edges: v.hiddenEdges
    })),
    annotations: dimensions.map(dim => ({
      id: dim.id,
      type: dim.type,
      mode: dim.mode ?? null,
      text: dim.text,
      customText: dim.customText ?? null,
      label: dim.label ?? null,
      bind_motor: dim.bind_motor ?? false,
      refs: dim.refs ?? [],
      // 孔组/特殊模式字段:不落盘的话换型号重绑会当成普通标注处理
      // (groupRefs 丢失=整条丢弃,diameterMode 丢失=引线渲染成贯穿直线)
      groupRefs: dim.groupRefs ?? null,
      diameterMode: dim.diameterMode ?? null,
      textLeft: dim.textLeft ?? null,
      textLeftLocal: dim.textLeftLocal ?? null,
      group: dim.group ?? null,
      groupCenter: dim.groupCenter ?? null,
      angleMode: dim.angleMode ?? null,
      extOvershoot: dim.extOvershoot ?? null,
      arrowMode: dim.arrowMode ?? null,
      spanMm: dim.spanMm ?? null,
      offset: dim.offset ?? null,
      textSlide: dim.textSlide ?? null,
      extensionStartPx: dim.extensionStartPx ?? null,
      extensionEndPx: dim.extensionEndPx ?? null,
      radius: dim.radius ?? null,
      side: dim.side ?? null,
      leaderAngle: dim.leaderAngle ?? null,
      leaderLength: dim.leaderLength ?? null,
      color: dim.color ?? null
    }))
  }
  // 表格:独立元素类型,与 views/annotations 并列;空则不写字段
  if (placedTables && placedTables.length) {
    doc.tables = placedTables.map(t => ({
      id: t.id,
      x: Math.round(t.x),
      y: Math.round(t.y),
      col_widths: t.col_widths,
      row_heights: t.row_heights,
      border: t.border,
      text_color: t.text_color,
      cells: t.cells
    }))
  }
  // 标题栏:字段带 source(模板变量)与 value(手动覆盖,优先于 source)
  if (titleBlock && titleBlock.fields && titleBlock.fields.length) {
    doc.title_block = {
      fields: titleBlock.fields.map(f => ({
        key: f.key,
        label: f.label,
        source: f.source ?? null,
        value: f.value ?? null,
        x: f.x ?? null,
        y: f.y ?? null
      }))
    }
  }
  // BOM:列定义 + 行;行可带 source 记录配置来源,便于配置变化时重建
  if (bomTable && bomTable.columns && bomTable.columns.length) {
    doc.bom_table = {
      x: bomTable.x ?? null,
      y: bomTable.y ?? null,
      columns: [...bomTable.columns],
      rows: (bomTable.rows || []).map(r => ({
        name: r.name ?? '',
        qty: r.qty ?? 1,
        code: r.code ?? null,
        material: r.material ?? null,
        source: r.source ?? null
      }))
    }
  }
  return doc
}

/** 预览用瘦身:edges/hidden_edges 只留条数,避免 <pre> 渲染几十万字符拖垮编辑器 */
export function previewDocument(doc) {
  return {
    ...doc,
    views: (doc.views || []).map(v => ({
      ...v,
      edges: `共 ${(v.edges || []).length} 条(预览省略)`,
      hidden_edges: `共 ${(v.hidden_edges || []).length} 条(预览省略)`
    }))
  }
}
