// 工程图文档 JSON 序列化(纯函数),供属性面板预览与保存模板复用
// px_per_mm: 调色板归一化比例(画布 px / 模型 mm),后端重算视图物理比例用
// customText: 用户自定义标注文字(如"减速机尺寸"),留空则显示测量值
// bind_motor: 线性标注绑定电机包络锚点,换电机时两端自动跟随新包络

export function buildDrawingDocument({ sheetSize, sheetWidth, sheetHeight, modelId, placedViews, dimensions }) {
  return {
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
      x: Math.round(v.x),
      y: Math.round(v.y),
      scale: Number(v.scale.toFixed(2)),
      px_per_mm: v.bbox?.scale ?? null
    })),
    annotations: dimensions.map(dim => ({
      id: dim.id,
      type: dim.type,
      mode: dim.mode ?? null,
      text: dim.text,
      customText: dim.customText ?? null,
      bind_motor: dim.bind_motor ?? false,
      refs: dim.refs,
      offset: dim.offset ?? null,
      radius: dim.radius ?? null,
      side: dim.side ?? null,
      leaderAngle: dim.leaderAngle ?? null,
      leaderLength: dim.leaderLength ?? null,
      color: dim.color ?? null
    }))
  }
}
