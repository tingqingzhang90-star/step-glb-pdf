// 标题栏与 BOM:右侧参数面板的数据与编辑。
// 字段值优先取手动覆盖 value,否则解析 source 里的 {{变量}};
// BOM 行可按当前选型配置重建,也可手动增删(手动行不带 source)。
import { ref } from 'vue'

// 与后端 rule_template/drawing_template.json 的 title_block 字段保持一致
const DEFAULT_TITLE_FIELDS = [
  { key: 'name', label: '图样名称', source: '{{series}}液压缸', value: null, x: 318, y: 262 },
  { key: 'model', label: '型号', source: '{{model_code}}', value: null, x: 318, y: 270 },
  { key: 'scale', label: '比例', source: '1:{{scale}}', value: null, x: 318, y: 278 },
  { key: 'stroke', label: '行程', source: '{{stroke}}mm', value: null, x: 360, y: 262 },
  { key: 'd1', label: '缸长D1', source: '{{d1}}mm', value: null, x: 360, y: 270 },
  { key: 'date', label: '日期', source: '{{date}}', value: null, x: 360, y: 278 }
]

const DEFAULT_BOM_COLUMNS = ['序号', '名称', '数量', '备注']

/** 用 params 解析 {{变量}};变量缺失时保留原占位,便于发现未绑定 */
export function resolveSource(source, params) {
  if (!source) return ''
  return String(source).replace(
    /\{\{\s*(\w+)\s*\}\}/g,
    (raw, name) => (params && params[name] != null ? String(params[name]) : raw)
  )
}

function defaultFields() {
  return DEFAULT_TITLE_FIELDS.map(f => ({ ...f }))
}

/**
 * 按选型配置生成 BOM 行:常显基础件 + 当前安装/负载/电机启用的受控件。
 * 同名零件合并数量,避免重复行。
 */
export function buildBomRows(config, modelParams) {
  if (!config) return []
  const picked = new Map()
  const add = (name, source) => {
    const key = String(name || '').trim()
    if (!key) return
    const hit = picked.get(key)
    if (hit) hit.qty += 1
    else picked.set(key, { name: key, qty: 1, code: null, material: null, source })
  }
  for (const name of config.base_parts || []) add(name, `base:${name}`)
  const groups = [['mount', modelParams?.mount], ['load', modelParams?.load], ['motor', modelParams?.motor]]
  for (const [group, code] of groups) {
    const entry = config[group]?.[code]
    for (const name of entry?.on || []) add(name, `config:${group}:${code}`)
  }
  return [...picked.values()]
}

export function useTitleBlockBom() {
  const titleBlock = ref({ fields: defaultFields() })
  const bomTable = ref({ x: 300, y: 200, columns: [...DEFAULT_BOM_COLUMNS], rows: [] })

  /** 字段最终显示值:手动覆盖优先,否则解析绑定来源 */
  function fieldValue(field, params) {
    if (field.value != null && field.value !== '') return field.value
    return resolveSource(field.source, params)
  }

  function setFieldValue(key, text) {
    const f = titleBlock.value.fields.find(x => x.key === key)
    if (f) f.value = text
  }

  function resetFieldValue(key) {
    const f = titleBlock.value.fields.find(x => x.key === key)
    if (f) f.value = null
  }

  function addField() {
    const n = titleBlock.value.fields.length + 1
    titleBlock.value.fields.push({
      key: `field_${n}`, label: `自定义${n}`, source: null, value: '', x: null, y: null
    })
  }

  function removeField(key) {
    titleBlock.value.fields = titleBlock.value.fields.filter(f => f.key !== key)
  }

  function addBomRow() {
    bomTable.value.rows.push({ name: '', qty: 1, code: null, material: null, source: null })
  }

  function removeBomRow(index) {
    bomTable.value.rows.splice(index, 1)
  }

  function rebuildBomFromConfig(config, modelParams) {
    bomTable.value.rows = buildBomRows(config, modelParams)
  }

  function loadFromDoc({ titleBlock: tb, bomTable: bt }) {
    titleBlock.value = tb && tb.fields && tb.fields.length
      ? { fields: tb.fields.map(f => ({ ...f })) }
      : { fields: defaultFields() }
    bomTable.value = bt && bt.columns
      ? {
          x: bt.x ?? 300,
          y: bt.y ?? 200,
          columns: [...bt.columns],
          rows: (bt.rows || []).map(r => ({ ...r }))
        }
      : { x: 300, y: 200, columns: [...DEFAULT_BOM_COLUMNS], rows: [] }
  }

  function reset() {
    titleBlock.value = { fields: defaultFields() }
    bomTable.value = { x: 300, y: 200, columns: [...DEFAULT_BOM_COLUMNS], rows: [] }
  }

  return {
    titleBlock, bomTable, fieldValue, setFieldValue, resetFieldValue,
    addField, removeField, addBomRow, removeBomRow,
    rebuildBomFromConfig, loadFromDoc, reset
  }
}
