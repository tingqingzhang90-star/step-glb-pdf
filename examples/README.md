# 最小出图示例

`quickstart.py` 用 `data/250-E-H2K1-L100-D55.brep` 这个真实的 250 系列 E 型装配体，走项目的 HLR 投影链路生成前视、左视、左视上视三个 SVG。只需要 `src/` 和 `requirements.txt`，不需要系列零件库、模板或任何客户数据。

```bash
conda create -n pdf1 python=3.10
conda activate pdf1
conda install -c conda-forge pythonocc-core
pip install -r requirements.txt
python examples/quickstart.py
```

产物在 `examples/output/`，该目录不入库：

| 文件 | 内容 |
| --- | --- |
| `front.svg` / `left.svg` / `left_top.svg` | 三个视图的 SVG 缩略图 |

换成自己的模型：

```bash
python examples/quickstart.py --step 路径/模型.step
```

示例模型是 OCC 的 BREP 拓扑缓存（约 3 MB，只有几何与拓扑，不含零件名称、型号或客户信息）。`core.drawing_engine.read_shape_cached` 支持 BREP-only 模式：脚本传入同名的 `.step` 路径，读取时自动回退到旁边的 `.brep`，因此仓库里不必再放一份体积更大的 STEP。

脚本调用 `generate_all_standard_views`，只投影模板常用的三个视图并关闭进程池，便于单机快速验证环境。想跑完整的「型号编码 → 装配重建 → 模板重绑 → PDF」链路，仍需按根目录 README 的「运行数据不入库」一节准备系列零件库与模板数据。
