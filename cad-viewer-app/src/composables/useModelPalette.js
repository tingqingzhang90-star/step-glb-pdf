// 型号选择与视图调色板数据加载
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchModelList, fetchViewPalette } from '@/api/drawingApi.js'

export function useModelPalette() {
  const models = ref([])
  const selectedModel = ref('')
  const loadingViews = ref(false)
  const viewsLoaded = ref(false)
  const loadingText = ref('')
  const error = ref('')
  const lastElapsed = ref(null)
  const modelBbox = ref({ width: 0, height: 0, depth: 0 })
  const paletteViews = ref({})
  const motorEnvelope = ref({})
  const gearboxEnvelope = ref({})

  const standardViews = computed(() =>
    Object.entries(paletteViews.value)
      .filter(([_, v]) => v.group === 'standard')
      .map(([name, v]) => ({ name, ...v }))
  )

  const isometricViews = computed(() =>
    Object.entries(paletteViews.value)
      .filter(([_, v]) => v.group === 'isometric')
      .map(([name, v]) => ({ name, ...v }))
  )

  async function loadModelList() {
    try {
      models.value = await fetchModelList()
    } catch (e) {
      error.value = '获取型号列表失败'
    }
  }

  /** 重置调色板数据(切换型号时由上层编排,同步清空已放置视图) */
  function resetPalette() {
    paletteViews.value = {}
    motorEnvelope.value = {}
    gearboxEnvelope.value = {}
    viewsLoaded.value = false
    error.value = ''
    lastElapsed.value = null
  }

  async function loadViewPalette() {
    if (!selectedModel.value) return
    loadingViews.value = true
    loadingText.value = '正在生成标准视图...'
    error.value = ''
    try {
      const data = await fetchViewPalette(selectedModel.value)
      if (!data.ok) {
        error.value = data.error || '生成视图失败'
        return
      }
      paletteViews.value = data.views
      motorEnvelope.value = data.motor_envelope || {}
      gearboxEnvelope.value = data.gearbox_envelope || {}
      modelBbox.value = data.model_bbox
      viewsLoaded.value = true
      lastElapsed.value = data.elapsed
      ElMessage.success(`已生成 ${Object.keys(data.views).length} 个视图, 耗时 ${data.elapsed}s`)
    } catch (e) {
      error.value = e.message || '加载失败'
    } finally {
      loadingViews.value = false
      loadingText.value = ''
    }
  }

  return {
    models, selectedModel, loadingViews, viewsLoaded, loadingText, error,
    lastElapsed, modelBbox, motorEnvelope, gearboxEnvelope,
    standardViews, isometricViews,
    loadModelList, resetPalette, loadViewPalette
  }
}
