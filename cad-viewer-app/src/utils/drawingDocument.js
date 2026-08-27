// 工程图文档 JSON 序列化(纯函数),供属性面板预览与后续导出复用

export function buildDrawingDocument({ sheetWidth, sheetHeight, modelId, placedViews, dimensions }) {
  return {
    sheet: {
      size: 'A0',
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
      scale: Number(v.scale.toFixed(2))
    })),
    annotations: dimensions.map(dim => ({
      id: dim.id,
      type: dim.type,
      text: dim.text,
      refs: dim.refs,
      offset: dim.offset ?? null,
      radius: dim.radius ?? null,
      side: dim.side ?? null,
      leaderAngle: dim.leaderAngle ?? null
    }))
  }
}
