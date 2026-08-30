<template>
  <el-dialog
    v-model="visible"
    title="模板出图"
    width="860px"
    :close-on-click-modal="false"
    append-to-body
  >
    <!-- 步骤 1: 选择模板 -->
    <el-steps :active="step" finish-status="success" simple class="td-steps">
      <el-step title="选择模板" />
      <el-step title="选择型号" />
      <el-step title="生成下载" />
    </el-steps>

    <!-- ---- 步骤 1 ---- -->
    <div v-if="step === 0" class="td-body">
      <el-tabs v-model="tplTab">
        <el-tab-pane label="从已保存模板选择" name="saved">
          <el-table
            :data="templates"
            highlight-current-row
            height="280"
            @current-change="onPickSaved"
          >
            <el-table-column prop="template_id" label="模板型号" min-width="200" />
            <el-table-column prop="identity" label="系列身份" width="150" />
            <el-table-column prop="view_count" label="视图" width="70" align="center" />
            <el-table-column prop="annotation_count" label="标注" width="70" align="center" />
          </el-table>
          <div class="td-hint">
            共 {{ templates.length }} 个模板。选中后点「下一步」。
          </div>
        </el-tab-pane>

        <el-tab-pane label="导入模板文件" name="upload">
          <el-upload
            drag
            accept=".json"
            :auto-upload="false"
            :limit="1"
            :on-change="onFileChange"
            :on-remove="onFileRemove"
          >
            <el-icon class="td-upload-icon"><UploadFilled /></el-icon>
            <div class="el-upload__text">
              拖入模板 JSON 文件,或<em>点击选择</em>
            </div>
            <template #tip>
              <div class="el-upload__tip">
                模板由本编辑器「保存为模板」导出,含 model_id / views / annotations
              </div>
            </template>
          </el-upload>
          <div v-if="uploadResult" class="td-upload-ok">
            已导入: {{ uploadResult.template_id }}
            (系列 {{ uploadResult.identity }},
            {{ uploadResult.annotation_count }} 条标注)
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>

    <!-- ---- 步骤 2 ---- -->
    <div v-else-if="step === 1" class="td-body">
      <div class="td-row">
        <span class="td-label">模板:</span>
        <el-tag type="primary">{{ templateId }}</el-tag>
        <span class="td-label" style="margin-left:16px">系列:</span>
        <el-tag type="success">{{ identity }}</el-tag>
      </div>
      <div class="td-row td-row-tight">
        <el-checkbox
          :model-value="allChecked"
          :indeterminate="indeterminate"
          @change="toggleAll"
        >
          全选({{ models.length }} 个同系列型号)
        </el-checkbox>
      </div>
      <el-checkbox-group v-model="selectedModels" class="td-checks">
        <el-checkbox
          v-for="m in models"
          :key="m.model_code"
          :value="m.model_code"
          class="td-check"
        >
          {{ m.model_code }}
          <el-tag v-if="m.has_pdf" size="small" type="info">已有PDF</el-tag>
        </el-checkbox>
      </el-checkbox-group>
      <div v-if="!models.length" class="td-hint td-warn">
        该系列下暂无可出图型号(需先生成装配体)
      </div>
      <div v-else class="td-hint">
        已选 {{ selectedModels.length }} 个。出图为同步执行,
        每张约需 5~15 秒(OCC 投影计算),请耐心等待。
      </div>
      <div v-if="generating" class="td-generating">
        <el-icon class="is-loading"><Loading /></el-icon>
        正在生成,请勿关闭页面…
      </div>
    </div>

    <!-- ---- 步骤 3 ---- -->
    <div v-else class="td-body">
      <el-table :data="results" height="300" v-loading="generating">
        <el-table-column prop="model_code" label="型号" min-width="200" />
        <el-table-column label="结果" width="90" align="center">
          <template #default="{ row }">
            <el-tag :type="row.ok ? 'success' : 'danger'" size="small">
              {{ row.ok ? '成功' : '失败' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="标注命中" min-width="180">
          <template #default="{ row }">
            <span v-if="!row.dims || !row.dims.length">—</span>
            <el-tooltip
              v-else
              placement="top"
              :content="dimSummary(row)"
            >
              <span>
                <el-tag
                  v-for="d in row.dims"
                  :key="d.id"
                  size="small"
                  :type="d.status === 'unmatched' ? 'danger' : 'success'"
                  class="td-dim-tag"
                >{{ d.id }}</el-tag>
              </span>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column prop="elapsed" label="耗时" width="80" align="center">
          <template #default="{ row }">{{ row.elapsed }}s</template>
        </el-table-column>
        <el-table-column label="操作" width="150" align="center">
          <template #default="{ row }">
            <template v-if="row.ok && row.pdf">
              <el-button link type="primary" size="small" @click="previewPdf(row)">查看</el-button>
              <el-button link type="primary" size="small" @click="downloadPdf(row)">下载</el-button>
            </template>
            <span v-else class="td-err">{{ row.error || '—' }}</span>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="unmatchedTotal" class="td-hint td-warn">
        {{ unmatchedTotal }} 条标注未匹配,PDF 内会以红色文字提示
      </div>
    </div>

    <template #footer>
      <div class="td-footer">
        <el-button v-if="step > 0 && step < 2" @click="step--">上一步</el-button>
        <el-button v-if="step === 2" @click="step = 1">返回重选</el-button>
        <el-button @click="close">关闭</el-button>
        <el-button
          v-if="step === 0"
          type="primary"
          :disabled="!templateId"
          @click="goModels"
        >下一步</el-button>
        <el-button
          v-else-if="step === 1"
          type="primary"
          :loading="generating"
          :disabled="!selectedModels.length"
          @click="doGenerate"
        >
          {{ generating ? '生成中…' : `生成 ${selectedModels.length} 张工程图` }}
        </el-button>
        <el-button v-else type="primary" @click="step = 0">再做一批</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled, Loading } from '@element-plus/icons-vue'
import {
  fetchDrawingTemplates, uploadDrawingTemplate,
  fetchSeriesModels, generateFromTemplate,
  pdfDownloadUrl, pdfPreviewUrl
} from '@/api/drawingApi'

const props = defineProps({ modelValue: Boolean })
const emit = defineEmits(['update:modelValue'])

const visible = computed({
  get: () => props.modelValue,
  set: v => emit('update:modelValue', v)
})

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
const unmatchedTotal = computed(
  () => results.value.reduce(
    (n, r) => n + (r.unmatched ? r.unmatched.length : 0), 0))

async function loadTemplates() {
  const data = await fetchDrawingTemplates()
  templates.value = data.ok ? (data.templates || []) : []
}

function onPickSaved(row) {
  if (!row) return
  templateId.value = row.template_id
  identity.value = row.identity
}

async function onFileChange(uploadFile) {
  const data = await uploadDrawingTemplate(uploadFile.raw)
  if (!data.ok) {
    ElMessage.error(data.error || '模板导入失败')
    return
  }
  uploadResult.value = data
  templateId.value = data.template_id
  identity.value = data.identity
  ElMessage.success(`模板已导入: ${data.template_id}`)
}

function onFileRemove() {
  uploadResult.value = null
  if (tplTab.value === 'upload') templateId.value = ''
}

async function goModels() {
  const data = await fetchSeriesModels({ templateId: templateId.value })
  if (!data.ok) {
    ElMessage.error(data.error || '获取同系列型号失败')
    return
  }
  identity.value = data.identity || identity.value
  models.value = data.models || []
  selectedModels.value = models.value.map(m => m.model_code)
  step.value = 1
}

function toggleAll(checked) {
  selectedModels.value = checked ? models.value.map(m => m.model_code) : []
}

async function doGenerate() {
  generating.value = true
  try {
    const data = await generateFromTemplate(
      templateId.value, selectedModels.value)
    if (!data.ok) {
      ElMessage.error(data.error || '出图失败')
      if (data.rejected && data.rejected.length) {
        ElMessage.warning(`已剔除不同系列型号: ${data.rejected.join(', ')}`)
      }
      return
    }
    results.value = data.results || []
    step.value = 2
    const okN = results.value.filter(r => r.ok).length
    ElMessage.success(`完成 ${okN}/${results.value.length} 张`)
  } finally {
    generating.value = false
  }
}

function dimSummary(row) {
  return (row.dims || []).map(d => `${d.id}: ${d.status}`).join('  ')
}

function downloadPdf(row) {
  window.open(pdfDownloadUrl(row.pdf), '_blank')
}

function previewPdf(row) {
  window.open(pdfPreviewUrl(row.pdf), '_blank')
}

function close() {
  visible.value = false
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

watch(visible, v => {
  if (v) {
    reset()
    loadTemplates()
  }
})
</script>

<style scoped>
.td-steps { margin-bottom: 16px; }
.td-body { min-height: 320px; }
.td-row { display: flex; align-items: center; margin-bottom: 10px; }
.td-row-tight { margin-bottom: 6px; }
.td-label { font-size: 13px; color: #606266; }
.td-checks { display: flex; flex-direction: column; gap: 2px; }
.td-check { height: 24px; }
.td-hint { margin-top: 10px; font-size: 12px; color: #909399; }
.td-warn { color: #e6a23c; }
.td-upload-icon { font-size: 40px; color: #c0c4cc; }
.td-upload-ok {
  margin-top: 10px; padding: 8px 12px; font-size: 13px;
  background: #f0f9eb; color: #67c23a; border-radius: 4px;
}
.td-dim-tag { margin-right: 3px; }
.td-generating {
  margin-top: 12px; padding: 8px 12px; font-size: 13px; color: #409eff;
  background: #ecf5ff; border-radius: 4px;
  display: flex; align-items: center; gap: 6px;
}
.td-err { font-size: 12px; color: #f56c6c; }
.td-footer { display: flex; justify-content: flex-end; gap: 8px; }
</style>
