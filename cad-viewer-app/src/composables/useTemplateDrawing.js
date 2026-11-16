// 模板出图向导的状态与流程控制(供 TemplateDrawingPanel 使用)
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import {
  fetchDrawingTemplates, uploadDrawingTemplate,
  fetchSeriesModels, generateFromTemplate
} from '@/api/drawingApi'

export function useTemplateDrawing() {
  const step = ref(0)
  const tplTab = ref('saved')
  const templates = ref([])
  const templateId = ref('')
  const identity = ref('')
  const models = ref([])
  const selectedModels = ref([])
  const results = ref([])
  const generating = ref(false)
  const uploadResult = ref(null)

  const allChecked = computed(
    () => models.value.length > 0 &&
          selectedModels.value.length === models.value.length)
  const indeterminate = computed(
    () => selectedModels.value.length > 0 &&
          selectedModels.value.length < models.value.length)
  const unmatchedTotal = computed(() => results.value.reduce(
    (n, r) => n + (r.unmatched ? r.unmatched.length : 0), 0))

  async function loadTemplates() {
    const data = await fetchDrawingTemplates()
    templates.value = data.ok ? (data.templates || []) : []
  }

  function pickSaved(row) {
    if (!row) return
    templateId.value = row.template_id
    identity.value = row.identity
  }

  async function uploadFile(file) {
    const data = await uploadDrawingTemplate(file)
    if (!data.ok) {
      ElMessage.error(data.error || '模板导入失败')
      return false
    }
    uploadResult.value = data
    templateId.value = data.template_id
    identity.value = data.identity
    ElMessage.success(`模板已导入: ${data.template_id}`)
    return true
  }

  function clearUpload() {
    uploadResult.value = null
    if (tplTab.value === 'upload') templateId.value = ''
  }

  async function loadModels() {
    const data = await fetchSeriesModels({ templateId: templateId.value })
    if (!data.ok) {
      ElMessage.error(data.error || '获取同系列型号失败')
      return false
    }
    identity.value = data.identity || identity.value
    models.value = data.models || []
    selectedModels.value = models.value.map(m => m.model_code)
    return true
  }

  function toggleAll(checked) {
    selectedModels.value = checked ? models.value.map(m => m.model_code) : []
  }

  async function generate() {
    generating.value = true
    try {
      const data = await generateFromTemplate(
        templateId.value, selectedModels.value)
      if (!data.ok) {
        ElMessage.error(data.error || '出图失败')
        if (data.rejected && data.rejected.length) {
          ElMessage.warning(`已剔除不同系列型号: ${data.rejected.join(', ')}`)
        }
        return false
      }
      results.value = data.results || []
      const okN = results.value.filter(r => r.ok).length
      ElMessage.success(`完成 ${okN}/${results.value.length} 张`)
      return true
    } finally {
      generating.value = false
    }
  }

  function reset() {
    step.value = 0
    tplTab.value = 'saved'
    templateId.value = ''
    identity.value = ''
    models.value = []
    selectedModels.value = []
    results.value = []
    uploadResult.value = null
  }

  return {
    step, tplTab, templates, templateId, identity,
    models, selectedModels, results, generating, uploadResult,
    allChecked, indeterminate, unmatchedTotal,
    loadTemplates, pickSaved, uploadFile, clearUpload,
    loadModels, toggleAll, generate, reset
  }
}
