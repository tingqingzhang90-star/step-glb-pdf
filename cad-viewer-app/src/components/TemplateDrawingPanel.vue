<template>
  <el-dialog
    v-model="visible"
    title="模板出图"
    width="860px"
    :close-on-click-modal="false"
    append-to-body
  >
    <el-steps :active="step" finish-status="success" simple class="td-steps">
      <el-step title="选择模板" />
      <el-step title="选择型号" />
      <el-step title="生成下载" />
    </el-steps>

    <!-- ---- 步骤 1: 选择模板 ---- -->
    <div v-if="step === 0" class="td-body">
      <el-tabs v-model="tplTab">
        <el-tab-pane label="从已保存模板选择" name="saved">
          <el-table
            :data="templates"
            highlight-current-row
            height="280"
            @current-change="pickSaved"
          >
            <el-table-column prop="template_id" label="模板型号" min-width="200" />
            <el-table-column prop="identity" label="系列身份" width="150" />
            <el-table-column prop="view_count" label="视图" width="70" align="center" />
            <el-table-column prop="annotation_count" label="标注" width="70" align="center" />
          </el-table>
          <div class="td-hint">共 {{ templates.length }} 个模板。选中后点「下一步」。</div>
        </el-tab-pane>

        <el-tab-pane label="导入模板文件" name="upload">
          <el-upload
            drag
            accept=".json"
            :auto-upload="false"
            :limit="1"
            :on-change="onFileChange"
            :on-remove="clearUpload"
          >
            <el-icon class="td-upload-icon"><UploadFilled /></el-icon>
            <div class="el-upload__text">拖入模板 JSON 文件,或<em>点击选择</em></div>
            <template #tip>
              <div class="el-upload__tip">
                模板由本编辑器「保存为模板」导出,含 model_id / views / annotations
              </div>
            </template>
          </el-upload>
          <div v-if="uploadResult" class="td-upload-ok">
            已导入: {{ uploadResult.template_id }}
            (系列 {{ uploadResult.identity }},{{ uploadResult.annotation_count }} 条标注)
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>

    <!-- ---- 步骤 2: 选择型号 ---- -->
    <div v-else-if="step === 1" class="td-body">
      <div class="td-row">
        <span class="td-label">模板:</span>
        <el-tag type="primary">{{ templateId }}</el-tag>
        <span class="td-label td-label-gap">系列:</span>
        <el-tag type="success">{{ identity }}</el-tag>
      </div>
      <div class="td-row td-row-tight">
        <el-checkbox
          :model-value="allChecked"
          :indeterminate="indeterminate"
          @change="toggleAll"
        >全选({{ models.length }} 个同系列型号)</el-checkbox>
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

    <!-- ---- 步骤 3: 生成下载 ---- -->
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
            <el-tooltip v-else placement="top" :content="dimSummary(row)">
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
        <el-table-column label="耗时" width="80" align="center">
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
import { computed, watch } from 'vue'
import { UploadFilled, Loading } from '@element-plus/icons-vue'
import { useTemplateDrawing } from '@/composables/useTemplateDrawing'
import { pdfDownloadUrl, pdfPreviewUrl } from '@/api/drawingApi'

const props = defineProps({ modelValue: Boolean })
const emit = defineEmits(['update:modelValue'])

const visible = computed({
  get: () => props.modelValue,
  set: v => emit('update:modelValue', v)
})

const {
  step, tplTab, templates, templateId, identity,
  models, selectedModels, results, generating, uploadResult,
  allChecked, indeterminate, unmatchedTotal,
  loadTemplates, pickSaved, uploadFile, clearUpload,
  loadModels, toggleAll, generate, reset
} = useTemplateDrawing()

async function onFileChange(uploadFile) {
  await uploadFile(uploadFile.raw)
}

async function goModels() {
  if (await loadModels()) step.value = 1
}

async function doGenerate() {
  if (await generate()) step.value = 2
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
.td-label-gap { margin-left: 16px; }
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
.td-err { font-size: 12px; color: #f56c6c; }
.td-generating {
  margin-top: 12px; padding: 8px 12px; font-size: 13px; color: #409eff;
  background: #ecf5ff; border-radius: 4px;
  display: flex; align-items: center; gap: 6px;
}
.td-footer { display: flex; justify-content: flex-end; gap: 8px; }
</style>
