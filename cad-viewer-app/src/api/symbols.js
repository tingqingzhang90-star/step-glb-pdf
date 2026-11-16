// SVG 符号库接口封装:上传 / 列表 / 取 URL(仅做请求与数据规整,不持有 UI 状态)

/** 上传一个 SVG 文件(multipart),返回 { ok, file, name, url } */
export async function uploadSymbol(file) {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch('/api/symbols/upload', { method: 'POST', body: form })
  return res.json()
}

/** 列出已上传符号,返回 { ok, symbols:[{file,name,url}] } */
export async function listSymbols() {
  const res = await fetch('/api/symbols')
  return res.json()
}

/** 单元格引用的是相对文件名,拼成可访问的 URL */
export function symbolUrl(file) {
  if (!file) return ''
  return `/api/symbols/${encodeURIComponent(file)}`
}
