// 规格回填(与后端 web/drawing_spec_map.py:apply_spec 保持一致,单点维护)
//
// 小程序以 ?src=...&spec=<JSON> 打开只读工程图时,客户端直接把 spec 写进
// doc.titleBlock.fields[].value 与 技术参数表 cells[].text,跳过后端 /api/render-drawing。
// 不改动 views / annotations 几何,只写可编辑内容。
//
// 说明:后端 apply_spec 依赖 series_cfg(系列配置,含缸长常数 C、电机 reducer/brand)。
// 该配置来自后端图库,客户端暂未内置;series_cfg 缺省时:
//   - 缸长 D1 不回填(几何相关,源文件自带)
//   - 电机安装方式/品牌型号降级为「方向 + 刹车」/电机 key 原值
// 其余字段(行程/功率/转速/减速比/推力/速度/型号等)均正常回填。

// 技术参数表中,标签 → (r, c) 的回填位置(与后端 PARAM_CELLS 一致)
// 注意:键含括号,JS 裸标识符不允许,必须加引号(与表格单元格 text 完全一致)
const PARAM_CELLS = {
  '产品型号': [1, 1],
  '有效行程(mm)': [2, 3],
  '电机功率(KW)': [3, 1],
  '额定转速(rpm)': [3, 3],
  '最高转速（rpm）': [4, 3],
  '丝杆导程（mm）': [5, 3],
  '减速比': [6, 1],
  '额定推力(KN)': [7, 1],
  '额定速度(mm/s)': [8, 1],
  '电机安装方式': [9, 1],
  '电机品牌型号': [10, 1],
  '其他说明': [11, 1]
}

export function parseModelCode(modelId) {
  const parts = String(modelId || '').split('-')
  if (parts.length < 4) return { series: parts[0] || '', type: '' }
  return { series: parts[0], type: parts[1] || '' }
}

function strokeNumber(modelId, spec) {
  const s = spec && spec.stroke
  if (s != null && String(s).trim() !== '') {
    return parseInt(parseFloat(String(s)), 10)
  }
  const m = /L(\d+)/.exec(modelId || '')
  return m ? parseInt(m[1], 10) : null
}

function formatMotorInstallation(modelId, motorKey, seriesCfg) {
  const sel = parseModelCode(modelId)
  const direction = (sel.type || '').toUpperCase() === 'F' ? '折返' : '直连'
  const parts = [direction]
  if (motorKey && String(motorKey).includes('刹车')) parts.push('带刹车')
  const reducer =
    seriesCfg && seriesCfg.motor && seriesCfg.motor[motorKey] && seriesCfg.motor[motorKey].reducer
  if (reducer) parts.push(`配${reducer}`)
  return parts.join(' ')
}

function formatMotorBrandModel(motorKey, seriesCfg) {
  const mc = seriesCfg && seriesCfg.motor && seriesCfg.motor[motorKey]
  if (mc && mc.brand && mc.model) return `${mc.brand} ${mc.model}`
  return motorKey || ''
}

function setTitleField(doc, key, value) {
  const fields = (doc.titleBlock && doc.titleBlock.fields) || []
  for (const f of fields) {
    if (f.key === key) {
      f.value = value
      return true
    }
  }
  return false
}

function findParamTable(doc) {
  for (const t of doc.tables || []) {
    for (const cell of t.cells || []) {
      if (cell.text === '技术参数') return t
    }
  }
  return null
}

function findCell(table, r, c) {
  for (const cell of table.cells || []) {
    if (cell.r === r && cell.c === c) return cell
  }
  return null
}

function setCell(table, r, c, text) {
  const cell = findCell(table, r, c)
  if (cell) {
    cell.text = text
    return true
  }
  return false
}

function formatDate() {
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

/**
 * 原地回填 spec 到解析后的 doc(parsed 形状:titleBlock/tables/modelId)。
 * 返回 doc。只写 title_block.fields[].value 与 技术参数表 cells[].text。
 * @param {object} doc parsed doc(来自 parseDrawingDocument)
 * @param {string} modelId 型号
 * @param {object} spec 小程序传来的规格(键同后端:stroke/motor/motorPower/...)
 * @param {object|null} seriesCfg 系列配置(可选,缺省降级)
 */
export function applySpec(doc, modelId, spec, seriesCfg = null) {
  if (!doc) return doc
  const sel = parseModelCode(modelId)
  const strokeNum = strokeNumber(modelId, spec)

  // ---- 标题栏 ----
  setTitleField(doc, 'model', modelId)
  if (strokeNum != null) setTitleField(doc, 'stroke', `${strokeNum}mm`)
  setTitleField(doc, 'name', `${sel.series}液压缸`)
  setTitleField(doc, 'scale', '1:1')
  setTitleField(doc, 'date', formatDate())
  if (strokeNum != null && seriesCfg) {
    const cConst = seriesCfg.cylinder && seriesCfg.cylinder.C
    if (cConst != null) setTitleField(doc, 'd1', `${strokeNum + parseInt(cConst, 10)}mm`)
  }

  // ---- 技术参数表 ----
  const table = findParamTable(doc)
  if (!table) return doc
  const put = (label, text) => {
    const rc = PARAM_CELLS[label]
    if (!rc) return
    setCell(table, rc[0], rc[1], text)
    // 保持值单元格字号与左侧标签一致,避免回填后字体大小不一
    const labelCell = findCell(table, rc[0], rc[1] - 1)
    const valueCell = findCell(table, rc[0], rc[1])
    if (labelCell && valueCell && labelCell.font_size != null) {
      valueCell.font_size = labelCell.font_size
    }
  }

  put('产品型号', modelId)
  if (strokeNum != null) put('有效行程(mm)', `${strokeNum}mm`)

  const motor = spec && spec.motor
  const motorPower = spec && spec.motorPower
  if (motorPower != null && String(motorPower) !== '') put('电机功率(KW)', String(motorPower))
  const rated = spec && spec.motorRatedSpeed
  if (rated != null && String(rated) !== '') put('额定转速(rpm)', String(rated))
  const maxsp = spec && spec.motorMaxSpeed
  if (maxsp != null && String(maxsp) !== '') put('最高转速（rpm）', String(maxsp))
  const travel = spec && spec.travel
  if (travel != null && String(travel) !== '') put('丝杆导程（mm）', `${travel}mm`)
  const ratio = spec && spec.reductionRatio
  if (ratio != null && String(ratio) !== '') put('减速比', String(ratio))

  const thrust = spec && spec.screwThrust
  if (thrust != null && thrust !== '') {
    const num = parseFloat(thrust)
    if (!Number.isNaN(num)) {
      const kn = num * 0.00980665
      put('额定推力(KN)', kn.toFixed(2))
    }
  }
  const speed = spec && spec.ratedSpeed
  if (speed != null && String(speed) !== '') put('额定速度(mm/s)', String(speed))

  if (motor) {
    put('电机安装方式', formatMotorInstallation(modelId, motor, seriesCfg))
    put('电机品牌型号', formatMotorBrandModel(motor, seriesCfg))
  }

  const remarkParts = []
  if (spec && spec.sizeStandard) remarkParts.push(String(spec.sizeStandard))
  if (spec && spec.remark) remarkParts.push(String(spec.remark))
  if (remarkParts.length) put('其他说明', remarkParts.join(' '))

  return doc
}
