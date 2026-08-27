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
