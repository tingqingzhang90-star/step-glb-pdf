# tools/ 临时脚本说明

`tools/_*.py` 与 `tools/*.out.*` 是**开发期一次性探针/调试脚本**,不属于项目正式代码,
也不参与任何产线流程。命名前缀 `_` 标识"临时",`*.out.*` 是脚本的输出产物。

这些文件**刻意保留在仓库中**而不删除,原因: 它们记录了当时验证过的结论(锚点实测值、
边线索引分布、中文字体方案等),重做同类排查时可直接复用,避免重复踩坑。

## 文件清单

| 文件 | 类型 | 用途 |
|---|---|---|
| `_probe_step_names.py` | 探针脚本 | 用 pythonOCC XCAF 读 `assembly.step`,验证 STEP 是否携带**零件名**,并遍历装配树提取各零件的 `bbox_min/bbox_max`。用于确认锚点(缸体端面、电机包络)能否按当前型号**实测**,而不必硬编码。 |
| `_probe_step_names.out.txt` | 输出产物 | 上者的遍历结果。当前内容止于 `[1] TDocStd_Document...`,说明该次运行在文档初始化阶段就中断了(未跑完),结论**未确立**,仅供后续续跑时对照。 |
| `_probe_make_fixture.py` | 探针脚本 | 从基准型号调色板里**反查真实边线下标**(缸体两端竖直边、电机区竖直边、最大圆),据此生成一份前端风格的实例模板 JSON 夹具,写入 `data/templates/engineering/<model_id>.json`。用于在没有前端界面的情况下,先跑通后端重绑/渲染管线。 |
| `_probe_pdf_cn.out.pdf` | 输出产物 | 中文字体渲染验证的 PDF 样本,确认 reportlab 输出中文(STSong-Light)不乱码。**注意**: 生成它的 `_probe_pdf_cn.py` 已删除,只剩产物;中文字体现已由 `src/dim_render.py` 的 `_ensure_font()` 统一处理。 |
| `_debug_frontend.py` | 调试脚本 | 完整走一遍 `generate_one_frontend` 流水线并打印**每一步中间状态**: 模板身份、基准边线数、位移补偿参数 `ctx`、视图放置 `placements`、单条标注重绑结果、以及 `build_dim_primitives` 输出的图元。用于定位"重绑失败"或"渲染空白"这类管线内部问题。 |

## 运行方式

必须在带 pythonOCC 的 conda 环境里跑(系统 Python 无 `OCC` 模块):

```
conda run -n pdf1 python tools/_debug_frontend.py
```

中文路径下 `conda run` 可能因 gbk 解码崩溃,可绕过 conda 包装层直接调用环境解释器:

```
set PYTHONIOENCODING=utf-8
C:\Users\<user>\.conda\envs\pdf1\python.exe tools/_debug_frontend.py
```

## 与正式代码的关系

正式管线是 `src/batch_drawing.py`(CLI 入口),配合 `src/frontend_template.py`(模板装载)、
`src/dim_rebind.py`(几何指纹重绑)、`src/dim_pdf_sheet.py`(PDF 渲染)。
上面这些 `tools/_*` 只是把正式管线的某个环节**拆开单跑 + 打印中间量**,不参与出图。

排查管线问题时,建议顺序:

1. 先看 `output/batch_report.json`(每条标注 matched/unmatched + 失配原因);
2. 仍定位不到,再跑 `_debug_frontend.py` 看中间量;
3. 涉及锚点实测或 STEP 元数据,跑 `_probe_step_names.py`;
4. 需要一份模板夹具做最小复现,跑 `_probe_make_fixture.py`。

## 注意

- 这些脚本里的型号编码、路径常量都是**写死的**,改型号需手动改脚本;
- 脚本会覆盖 `data/templates/engineering/` 下同名模板文件(`_probe_make_fixture.py`),
  若该型号已有前端保存的真实模板,跑之前先备份;
- 已验证完的结论请写进 `docs/`,不要只留在脚本注释里。
