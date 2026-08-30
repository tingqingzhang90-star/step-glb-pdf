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

// ===== 模板出图:导入模板 → 选同系列型号 → 生成 → 下载 =====

/** 上传模板文件(前端导出的实例模板 JSON) */
export async function uploadDrawingTemplate(file) {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch('/api/template-drawing/upload', {
    method: 'POST',
    body: form
  })
  return res.json()
}

/** 列出与模板同系列、且已生成过模型的全部型号 */
export async function fetchSeriesModels({ identity, templateId } = {}) {
  const qs = new URLSearchParams()
  if (identity) qs.set('identity', identity)
  if (templateId) qs.set('template_id', templateId)
  const res = await fetch(`/api/template-drawing/series-models?${qs}`)
  return res.json()
}

/** 用模板对选定型号批量出图 */
export async function generateFromTemplate(templateId, models) {
  const res = await fetch('/api/template-drawing/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ template_id: templateId, models })
  })
  return res.json()
}

/** PDF 下载地址(pdf 为相对项目根路径) */
export function pdfDownloadUrl(pdfRelPath) {
  return `/api/template-drawing/download/${pdfRelPath}`
}

export function pdfPreviewUrl(pdfRelPath) {
  return `/api/template-drawing/preview/${pdfRelPath}`
}
