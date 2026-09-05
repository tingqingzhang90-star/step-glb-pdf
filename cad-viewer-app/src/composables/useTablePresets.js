// 表格预设:把当前图纸上的整套表格存进 localStorage,下次一键按原坐标灌回。
// 图纸幅面在存/取两侧一致(如都是 A3),坐标可以直接复用,不需要重排。
// 与"图纸模板"(整图 + 批量出图,走后端)是两码事,互不干扰。
import { ref } from 'vue'
import { ElMessage } from 'element-plus'

const STORAGE_KEY = 'table-presets'

export function useTablePresets() {
  const presets = ref([])

  /** 读本地预设。数据损坏时清空并提示,不让脏数据卡死后续写入 */
  function load() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      presets.value = raw ? JSON.parse(raw) : []
    } catch (e) {
      presets.value = []
      ElMessage.warning(`表格预设读取失败,已重置:${e.message}`)
    }
  }

  function write() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(presets.value))
      return true
    } catch (e) {
      ElMessage.error(`表格预设写入失败:${e.message}`)
      return false
    }
  }

  /** 存一整套表格。返回是否成功,失败原因已通过 ElMessage 告知 */
  function save(name, tables) {
    const trimmed = (name || '').trim()
    if (!trimmed) {
      ElMessage.warning('请输入模板名称')
      return false
    }
    if (!tables.length) {
      ElMessage.warning('当前图纸上没有表格可保存')
      return false
    }
    if (presets.value.some(p => p.name === trimmed)) {
      ElMessage.warning(`已存在同名模板「${trimmed}」`)
      return false
    }
    presets.value.push({
      id: `preset_${Date.now()}`,
      name: trimmed,
      createdAt: new Date().toISOString(),
      // 深拷贝断开与画布的引用,否则之后改画布会连预设一起改掉
      tables: JSON.parse(JSON.stringify(tables))
    })
    return write()
  }

  /** 按原坐标把预设里的表格逐个放回画布,返回放入张数 */
  function apply(id, placeTable) {
    const p = presets.value.find(x => x.id === id)
    if (!p) return 0
    for (const t of p.tables) placeTable(t, t.x, t.y)
    return p.tables.length
  }

  function remove(id) {
    presets.value = presets.value.filter(p => p.id !== id)
    write()
  }

  return { presets, load, save, apply, remove }
}
