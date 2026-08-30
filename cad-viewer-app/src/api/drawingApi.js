// 后端接口封装:仅做请求与数据规整,不持有 UI 状态

export async function fetchModelList() {
  const res = await fetch('/api/files')
  const data = await res.json()
  const models = []
  if (data.groups) {
    for (const g of data.groups) {
      const names = (g.files || []).map(f => f.name)
      if (names.includes('assembly.step') || names.includes('assembly.brep')) {
        models.push(g.model)
      }
    }
  }
  return models
}

export async function fetchViewPalette(modelId) {
  const res = await fetch(`/api/drawing-view-palette/${modelId}`)
  return res.json()
}

// 保存为模板:后端落盘 data/templates/engineering/<model_id>.json
export async function saveDrawingTemplate(doc) {
  const res = await fetch('/api/drawing-template', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(doc)
  })
  return res.json()
}

export async function fetchDrawingTemplates() {
  const res = await fetch('/api/drawing-templates')
  return res.json()
}
