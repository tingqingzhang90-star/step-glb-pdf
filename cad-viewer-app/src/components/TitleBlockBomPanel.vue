<template>
  <div>
    <el-space>
      <el-text strong>标题栏</el-text>
      <el-button size="small" text @click="addField">+ 字段</el-button>
    </el-space>

    <el-form label-position="top" size="small">
      <el-form-item v-for="f in titleFields" :key="f.key">
        <template #label>
          <el-space :size="4">
            <el-text>{{ f.label }}</el-text>
            <el-tag v-if="f.source" size="small" type="info" effect="plain">{{ f.source }}</el-tag>
            <el-tag v-else size="small" effect="plain">手动</el-tag>
          </el-space>
        </template>
        <el-space>
          <el-input
            :model-value="fieldValue(f, modelParams)"
            :placeholder="f.source ? '' : '未绑定来源,直接填写'"
            @update:model-value="v => setFieldValue(f.key, v)"
          />
          <el-button v-if="f.value" size="small" text @click="resetFieldValue(f.key)">恢复绑定</el-button>
          <el-button size="small" text type="danger" @click="removeField(f.key)">删</el-button>
        </el-space>
      </el-form-item>
    </el-form>

    <el-divider />

    <el-space>
      <el-text strong>BOM 物料表</el-text>
      <el-button size="small" text @click="addBomRow">+ 行</el-button>
      <el-button
        size="small"
        type="primary"
        :disabled="!config"
        @click="rebuildBomFromConfig(config, modelParams)"
      >按配置重建</el-button>
    </el-space>

    <el-table :data="bomRows" size="small" border max-height="240">
      <el-table-column type="index" label="序号" width="50" align="center" />
      <el-table-column label="名称" min-width="120">
        <template #default="{ row }">
          <el-input v-model="row.name" size="small" />
        </template>
      </el-table-column>
      <el-table-column label="数量" width="92">
        <template #default="{ row }">
          <el-input-number v-model="row.qty" size="small" :min="1" controls-position="right" />
        </template>
      </el-table-column>
      <el-table-column label="来源" min-width="96">
        <template #default="{ row }">
          <el-text type="info" size="small">{{ row.source ? '配置' : '手动' }}</el-text>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="56" align="center">
        <template #default="{ $index }">
          <el-button size="small" text type="danger" @click="removeBomRow($index)">删</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-text v-if="!config" type="info" size="small">
      未加载选型配置,可手动编辑行;导入型号后可按配置自动重建。
    </el-text>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  titleBlockBom: { type: Object, required: true },
  config: { type: Object, default: null },
  modelParams: { type: Object, default: () => ({}) }
})

const {
  titleBlock, bomTable, fieldValue, setFieldValue, resetFieldValue,
  addField, removeField, addBomRow, removeBomRow, rebuildBomFromConfig
} = props.titleBlockBom

const titleFields = computed(() => titleBlock.value.fields)
const bomRows = computed(() => bomTable.value.rows)
</script>
