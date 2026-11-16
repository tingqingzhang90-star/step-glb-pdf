// 源文件(JSON)解析:校验 schema 版本 + 适配为各 composable 期望的对象形状。
// 与 buildDrawingDocument 互逆:序列化出去的 doc,这里能原样灌回画布。
// 视图几何(edges/hiddenEdges/bbox/contentBBox)直接还原,无需后端重新投影。

export function parseDrawingDocument(raw) {
  const doc = typeof raw === 'string' ? JSON.parse(raw) : raw
  if (!doc || typeof doc !== 'object') throw new Error('源文件格式无效(应为 JSON 对象)')
  const ver = String(doc.schema_version || '0')
  if (!ver.startsWith('1.')) {
    throw new Error(`不支持的 schema 版本: ${ver}(需要 1.x)`)
  }

  // 视图:doc.views[].source_view/edges/hidden_edges → composable 的 name/edges/hiddenEdges
  // id 必须原样保留:标注的 refs[].viewId 指向它,重新生成会让全部标注失配
  const views = (doc.views || []).map(v => ({
    id: v.id,
    name: v.source_view,
    label: v.label,
    group: v.group ?? null,
    edges: v.edges || [],
    hiddenEdges: v.hidden_edges || [],
    bbox: v.bbox || null,
    contentBBox: v.contentBBox || null,
    x: v.x,
    y: v.y,
    scale: v.scale
  }))

  // 标注:字段名与 composable 的 dim 对象一致,直接展开。
  // 过滤掉引用了不存在视图的悬空标注,否则导入后渲染不出且难以排查
  const viewIds = new Set(views.map(v => v.id))
  const annotationsRaw = doc.annotations || []
  const dimensions = annotationsRaw
    .filter(d => (d.refs || []).every(r => viewIds.has(r.viewId))
      && (d.groupRefs || []).every(r => viewIds.has(r.viewId)))
    .map(d => ({ ...d }))
  const droppedAnnotations = annotationsRaw.length - dimensions.length

  // 表格:doc.tables 字段名与 composable 的 table 对象一致,直接展开
  const tables = (doc.tables || []).map(t => ({ ...t }))

  // 标题栏:字段直接展开;空则给空 fields,由上层决定是否用默认模板
  const titleBlock = doc.title_block
    ? { fields: (doc.title_block.fields || []).map(f => ({ ...f })) }
    : { fields: [] }

  // BOM:列定义 + 行直接展开
  const bomTable = doc.bom_table
    ? {
        columns: [...(doc.bom_table.columns || [])],
        rows: (doc.bom_table.rows || []).map(r => ({ ...r }))
      }
    : { columns: [], rows: [] }

  return {
    sheet: doc.sheet || null,
    modelId: doc.model_id || null,
    views,
    dimensions,
    droppedAnnotations,
    tables,
    titleBlock,
    bomTable
  }
}

/** 把解析结果灌入编辑器各 composable(精确还原,免重投影) */
export function applyDrawingDocument(parsed, { placedViews, dimensions, placedTables, titleBlockBom }) {
  if (parsed.views && parsed.views.length) placedViews.setViews(parsed.views)
  if (parsed.dimensions && parsed.dimensions.length) dimensions.setDimensions(parsed.dimensions)
  if (parsed.tables && parsed.tables.length) placedTables.setTables(parsed.tables)
  if (titleBlockBom) titleBlockBom.loadFromDoc(parsed)
}
