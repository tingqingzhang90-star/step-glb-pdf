// 表格模板:把当前图纸上的整套表格存到后端,下次一键按原坐标灌回。
// 幅面在存/取两侧一致(如都是 A3),坐标可以直接复用,不需要重排。
// 与"图纸模板"(整图 + 批量出图)是两码事,互不干扰。后端全局共享,不绑定型号。
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  fetchTablePresets,
  saveTablePreset,
  deleteTablePreset
} from '@/api/drawingApi'

export function useTablePresets() {
  const presets = ref([])
  const loading = ref(false)

  async function load() {
    loading.value = true
    try {
      const data = await fetchTablePresets()
      presets.value = data.presets || []
    } catch (e) {
      ElMessage.error(`表格模板加载失败:${e.message || e}`)
      presets.value = []
    } finally {
      loading.value = false
    }
  }

  async function save(name, tables) {
    const trimmed = (name || '').trim()
    if (!trimmed) {
      ElMessage.warning('请输入模板名称')
      return false
    }
    if (!tables.length) {
      ElMessage.warning('当前图纸上没有表格可保存')
      return false
    }
    try {
      const data = await saveTablePreset(trimmed, tables)
      // 深拷贝断开与画布的引用,之后改画布不会连预设一起改掉
      presets.value.push({
        id: data.id,
        name: data.name,
        createdAt: data.createdAt,
        tables: JSON.parse(JSON.stringify(tables))
      })
      return true
    } catch (e) {
      ElMessage.error(`保存失败:${e.message || e}`)
      return false
    }
  }

  // 按原坐标把模板里的表格逐个放回画布,返回放入张数(纯本地,数据已在列表里)
  function apply(id, placeTable) {
    const p = presets.value.find(x => x.id === id)
    if (!p) return 0
    for (const t of p.tables) placeTable(t, t.x, t.y)
    return p.tables.length
  }

  async function remove(id) {
    try {
      await deleteTablePreset(id)
      presets.value = presets.value.filter(p => p.id !== id)
      return true
    } catch (e) {
      ElMessage.error(`删除失败:${e.message || e}`)
      return false
    }
  }

  return { presets, loading, load, save, apply, remove }
}
