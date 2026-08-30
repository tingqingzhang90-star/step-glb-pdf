# -*- coding: utf-8 -*-
"""可视化操作面板：按选型参数生成装配体 STEP/GLB

功能:
    - 浏览器表单选择 系列/连接类型/安装方式/负载连接/行程/电机编号
    - 实时拼接型号编码预览
    - 一键调用 build_assembly 生成装配体(文件名带型号,不覆盖)
    - 显示耗时分解、显示/抑制件数、D1/缩放、下载链接
    - 已生成文件列表,支持下载

启动:
    conda run -n pdf1 python src/server.py
    # 浏览器打开 http://127.0.0.1:5001

依赖:
    flask, pythonocc-core, trimesh, openpyxl(仅重建配置时)
"""
import os
import sys
import json
import glob
import threading

# 本文件位于 src/web/,需把 src 加入 sys.path 才能导入 core/drawing 包
_HERE = os.path.dirname(os.path.abspath(__file__))          # src/web
_SRC_DIR = os.path.dirname(_HERE)                            # src
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from flask import (Flask, request, jsonify, send_from_directory,
                   send_file, render_template_string)

from core import rebuild_assembly as rb

_PROJECT_ROOT = os.path.dirname(_SRC_DIR)
OUT_DIR = rb.OUT_DIR
CONFIG_DIR = rb.CONFIG_DIR
# 3D 查看器相关路径(viewer.html 与 o3dv 静态资源均位于 src/web/ 下)
_STATIC_DIR = os.path.join(_HERE, "static")
_VIEWER_HTML = os.path.join(_HERE, "viewer.html")
_DRAWING_EDITOR_HTML = os.path.join(_HERE, "drawing_editor.html")

app = Flask(__name__)

# pythonOCC 非线程安全,串行化构建请求
_build_lock = threading.Lock()


# ===================== 前端页面(内嵌单文件) =====================
HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>装配体生成面板</title>
<style>
  :root{
    --bg:#0f1419; --panel:#1a2029; --panel2:#222b36; --border:#2d3744;
    --txt:#e4e7eb; --txt2:#9aa5b1; --accent:#3b82f6; --accent2:#10b981;
    --warn:#f59e0b; --err:#ef4444; --ok:#22c55e;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:-apple-system,"Microsoft YaHei",Segoe UI,Roboto,sans-serif;
       background:var(--bg);color:var(--txt);min-height:100vh;padding:20px}
  h1{font-size:20px;margin-bottom:16px;display:flex;align-items:center;gap:10px}
  h1 .dot{width:10px;height:10px;border-radius:50%;background:var(--accent2);box-shadow:0 0 8px var(--accent2)}
  .wrap{max-width:1200px;margin:0 auto;display:grid;grid-template-columns:420px 1fr;gap:20px}
  @media(max-width:900px){.wrap{grid-template-columns:1fr}}
  .card{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:18px}
  .card h2{font-size:15px;color:var(--txt2);margin-bottom:14px;font-weight:600;
           text-transform:uppercase;letter-spacing:.5px}
  .field{margin-bottom:14px}
  .field label{display:block;font-size:13px;color:var(--txt2);margin-bottom:6px}
  .field select,.field input{width:100%;padding:9px 11px;background:var(--panel2);
       border:1px solid var(--border);border-radius:7px;color:var(--txt);font-size:14px;outline:none}
  .field select:focus,.field input:focus{border-color:var(--accent)}
  .row2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
  .code-box{background:var(--panel2);border:1px dashed var(--border);border-radius:8px;
            padding:14px;margin:6px 0 16px;text-align:center}
  .code-box .lbl{font-size:12px;color:var(--txt2);margin-bottom:6px}
  .code-box .code{font-size:20px;font-weight:700;color:var(--accent2);
                  font-family:Consolas,Monaco,monospace;word-break:break-all}
  .hint{font-size:12px;color:var(--txt2);margin-top:6px}
  .hint b{color:var(--accent)}
  .btn{width:100%;padding:12px;background:var(--accent);color:#fff;border:none;
       border-radius:8px;font-size:15px;font-weight:600;cursor:pointer;transition:.15s}
  .btn:hover{background:#2563eb}
  .btn:disabled{background:#475569;cursor:not-allowed}
  .btn.building{background:var(--warn)}
  .spinner{display:inline-block;width:14px;height:14px;border:2px solid #fff3;
           border-top-color:#fff;border-radius:50%;animation:spin .7s linear infinite;vertical-align:middle;margin-right:8px}
  @keyframes spin{to{transform:rotate(360deg)}}
  .result{margin-top:16px}
  .result .empty{color:var(--txt2);font-size:13px;text-align:center;padding:30px 0}
  .stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:14px}
  .stat{background:var(--panel2);border-radius:8px;padding:12px;text-align:center}
  .stat .v{font-size:22px;font-weight:700;color:var(--accent2)}
  .stat .v.err{color:var(--err)}
  .stat .l{font-size:11px;color:var(--txt2);margin-top:4px}
  .times{width:100%;border-collapse:collapse;font-size:13px;margin-bottom:14px}
  .times td,.times th{padding:7px 10px;text-align:left;border-bottom:1px solid var(--border)}
  .times th{color:var(--txt2);font-weight:600;width:60%}
  .times td{text-align:right;font-family:Consolas,monospace}
  .files{margin-top:10px}
  .file{display:flex;align-items:center;justify-content:space-between;
        padding:9px 12px;background:var(--panel2);border-radius:7px;margin-bottom:7px;font-size:13px}
  .file .nm{font-family:Consolas,monospace;color:var(--txt);word-break:break-all}
  .file .sz{color:var(--txt2);font-size:12px;margin-left:8px;white-space:nowrap}
  .file a{color:var(--accent);text-decoration:none;font-size:12px;margin-left:10px;white-space:nowrap}
  .file a:hover{text-decoration:underline}
  .file a.view-link{color:var(--accent2)}
  .grp{margin-bottom:14px}
  .grp-hd{font-size:13px;font-weight:600;color:var(--accent);margin-bottom:7px;
          padding-bottom:5px;border-bottom:1px solid var(--border);
          cursor:pointer;user-select:none;transition:.15s}
  .grp-hd:hover{background:#1e2a3a;border-radius:4px;padding:4px 6px;margin:-4px -6px 3px}
  .grp-hd.clickable::after{content:' 📋';font-size:11px;opacity:.5}
  .grp-cnt{font-size:11px;color:var(--txt2);font-weight:400;margin-left:6px}
  .dl-row{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px}
  .dl-row a{flex:1;min-width:140px;text-align:center;padding:10px;background:var(--panel2);
            border:1px solid var(--border);border-radius:7px;color:var(--accent);text-decoration:none;font-size:13px}
  .dl-row a:hover{border-color:var(--accent);background:#1e2a3a}
  .dl-row a.view-link{color:var(--accent2);border-color:var(--accent2)}
  .dl-row a.view-link:hover{background:#0f2a1a}
  .err-msg{background:#3b1219;border:1px solid var(--err);color:#fecaca;
           padding:12px;border-radius:8px;font-size:13px;margin-top:12px;white-space:pre-wrap}
  .ok-msg{background:#0f2a1a;border:1px solid var(--ok);color:#bbf7d0;
          padding:12px;border-radius:8px;font-size:13px;margin-bottom:14px}
  .badge{display:inline-block;font-size:11px;padding:2px 8px;border-radius:10px;
         background:#1e3a5f;color:#93c5fd;margin-left:6px}
</style>
</head>
<body>
<h1><span class="dot"></span>装配体生成面板 <span class="badge">pythonOCC</span></h1>
<div class="wrap">
  <!-- 左:参数表单 -->
  <div class="card">
    <h2>选型参数</h2>
    <div class="field">
      <label>系列</label>
      <select id="series"></select>
    </div>
    <div class="row2">
      <div class="field">
        <label>连接类型</label>
        <select id="type">
          <option value="E">E - 直连</option>
          <option value="F">F - 折返</option>
        </select>
      </div>
      <div class="field">
        <label>电机编号</label>
        <select id="motorCode"></select>
      </div>
    </div>
    <div class="row2">
      <div class="field">
        <label>安装方式</label>
        <select id="mount"></select>
      </div>
      <div class="field">
        <label>负载连接</label>
        <select id="load"></select>
      </div>
    </div>
    <div class="field">
      <label>行程 (mm)</label>
      <input id="strokeNum" type="number" min="100" max="2000" step="1" value="100">
      <div class="hint">行程范围 100~714，D1 = 行程 + <b id="cVal">340</b> = <b id="d1Val">440</b> mm</div>
    </div>
    <div class="code-box">
      <div class="lbl">型号编码</div>
      <div class="code" id="codePreview">250-E-H2K1-L100-D11</div>
    </div>
    <button class="btn" id="buildBtn" onclick="doBuild()">生成装配体</button>
  </div>

  <!-- 右:结果 + 文件列表 -->
  <div class="card">
    <h2>生成结果</h2>
    <div id="resultArea"><div class="empty">选择参数后点击「生成装配体」</div></div>
    <h2 style="margin-top:22px">已生成文件 <span class="badge" id="fileCount">0</span></h2>
    <div class="files" id="fileList"></div>
  </div>
</div>

<script>
let OPTS = null;

async function loadOptions(){
  const r = await fetch('/api/options');
  OPTS = await r.json();
  // 系列
  const sel = document.getElementById('series');
  sel.innerHTML = OPTS.series.map(s=>`<option value="${s.name}">${s.name}</option>`).join('');
  // 电机编号
  const mc = document.getElementById('motorCode');
  mc.innerHTML = OPTS.motor_codes.map(m=>`<option value="${m.code}">${m.code} - ${m.name}</option>`).join('')
    + `<option value="">不编入型号(--motor 回退)</option>`;
  mc.value = 'D11';
  sel.addEventListener('change', onSeriesChange);
  document.getElementById('type').addEventListener('change', updateCode);
  document.getElementById('motorCode').addEventListener('change', updateCode);
  document.getElementById('mount').addEventListener('change', updateCode);
  document.getElementById('load').addEventListener('change', updateCode);
  document.getElementById('strokeNum').addEventListener('input', updateCode);
  onSeriesChange();
  loadFiles();
}

function onSeriesChange(){
  const name = document.getElementById('series').value;
  const s = OPTS.series.find(x=>x.name===name);
  if(!s) return;
  fillSelect('mount', s.mount.length?s.mount:['H2']);
  fillSelect('load', s.load.length?s.load:['K1']);
  // 行程范围
  const strokes = s.strokes;
  if(strokes.length){
    const nums = strokes.map(x=>parseInt(x.replace(/^L/,''))).filter(x=>!isNaN(x));
    const inp = document.getElementById('strokeNum');
    inp.min = Math.min(...nums);
    inp.max = Math.max(...nums);
    if(parseInt(inp.value) < inp.min) inp.value = inp.min;
    if(parseInt(inp.value) > inp.max) inp.value = inp.max;
  }
  updateCode();
}

function fillSelect(id, arr){
  const el = document.getElementById(id);
  el.innerHTML = arr.map(v=>`<option value="${v}">${v}</option>`).join('');
}

function updateCode(){
  const series = document.getElementById('series').value.replace(/[^\d]/g,'');
  const type = document.getElementById('type').value;
  const mount = document.getElementById('mount').value;
  const load = document.getElementById('load').value;
  const strokeNum = document.getElementById('strokeNum').value || '100';
  const mc = document.getElementById('motorCode').value;
  const code = `${series}-${type}-${mount}${load}-L${strokeNum}` + (mc?`-${mc}`:'');
  document.getElementById('codePreview').textContent = code;
  // D1 预览
  const c = parseInt(document.getElementById('cVal').textContent) || 340;
  document.getElementById('d1Val').textContent = (parseInt(strokeNum)||0) + c;
}

async function doBuild(){
  const btn = document.getElementById('buildBtn');
  const area = document.getElementById('resultArea');
  const code = document.getElementById('codePreview').textContent;
  const seriesName = document.getElementById('series').value;
  const mc = document.getElementById('motorCode').value;
  btn.disabled = true; btn.classList.add('building');
  btn.innerHTML = '<span class="spinner"></span>生成中...';
  area.innerHTML = '<div class="empty"><span class="spinner"></span>正在装配,约 10~20 秒...</div>';
  try{
    const body = {model_code: code, series: seriesName};
    if(!mc){
      // 无电机编号,传 motor 回退(取 D11 对应的中文名)
      body.motor = '11kw电机';
    }
    const r = await fetch('/api/build',{
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(body)
    });
    const data = await r.json();
    if(!data.ok){
      area.innerHTML = `<div class="err-msg">生成失败:\n${data.error||'未知错误'}</div>`;
    } else {
      renderResult(data.result);
      loadFiles();
    }
  }catch(e){
    area.innerHTML = `<div class="err-msg">请求异常: ${e}</div>`;
  }finally{
    btn.disabled = false; btn.classList.remove('building');
    btn.innerHTML = '生成装配体';
  }
}

function renderResult(r){
  const t = r.times;
  const dlLinks = [];
  if(r.step_file) dlLinks.push(`<a href="/download/${encodeURIComponent(r.step_file)}" download>↓ 装配体 STEP</a>`);
  if(r.glb_file) dlLinks.push(`<a href="/download/${encodeURIComponent(r.glb_file)}" download>↓ 装配体 GLB</a>`);
  if(r.cylinder_file) dlLinks.push(`<a href="/download/${encodeURIComponent(r.cylinder_file)}" download>↓ 缸体 STEP</a>`);
  // 查看模型按钮(仅 GLB 可被 o3dv 渲染),新标签页打开 3D 查看器
  const viewLinks = [];
  if(r.glb_file){
    const modelUrl = encodeURIComponent('/download/' + r.glb_file);
    const productName = encodeURIComponent(r.model_code || '装配体');
    viewLinks.push(`<a class="view-link" href="/viewer?modelUrl=${modelUrl}&productName=${productName}" target="_blank">👁 查看模型</a>`);
  }
  // 工程图按钮(新标签页打开工程图编辑器)
  if(r.step_file){
    viewLinks.push(`<a class="view-link" href="/drawing" target="_blank">📐 工程图</a>`);
  }
  document.getElementById('resultArea').innerHTML = `
    <div class="ok-msg">✓ 生成完成: <b>${r.model_code}</b> · 系列 ${r.series} · 电机 ${r.motor}</div>
    <div class="dl-row">${dlLinks.join('')}${viewLinks.join('')}</div>
    <div class="stats">
      <div class="stat"><div class="v">${r.total_time}s</div><div class="l">总耗时</div></div>
      <div class="stat"><div class="v">${r.shown}</div><div class="l">显示件数</div></div>
      <div class="stat"><div class="v">${r.hidden}</div><div class="l">抑制件数</div></div>
      <div class="stat"><div class="v">${r.d1!=null?r.d1:'-'}</div><div class="l">缸体 D1</div></div>
    </div>
    <table class="times">
      <tr><th>Step 1 读取零件 STEP</th><td>${t.read}s</td></tr>
      <tr><th>缸体拉伸(主流程)</th><td>${(t.stretch*1000)|0}ms</td></tr>
      <tr><th>Step 2 应用变换+合并</th><td>${(t.merge*1000)|0}ms</td></tr>
      <tr><th>Step 3 导出装配体 STEP</th><td>${t.step}s</td></tr>
      <tr><th>Step 4 缸体拉伸验证</th><td>${(t.cylinder*1000)|0}ms</td></tr>
      <tr><th>Step 5 GLB 导出</th><td>${t.glb}s</td></tr>
    </table>
  `;
}

async function loadFiles(){
  const r = await fetch('/api/files');
  const data = await r.json();
  const list = document.getElementById('fileList');
  document.getElementById('fileCount').textContent = data.total;
  if(!data.groups.length){
    list.innerHTML = '<div class="empty" style="padding:14px">暂无文件</div>';
    return;
  }
  list.innerHTML = data.groups.map(g=>`
    <div class="grp">
      <div class="grp-hd${g.has_info?' clickable':''}" onclick="${g.has_info?`loadHistory('${g.model}')`:''}">${g.model} <span class="grp-cnt">${g.files.length} 件</span></div>
      ${g.files.map(f=>{
        const isGlb = f.name.toLowerCase().endsWith('.glb');
        const viewLink = isGlb
          ? `<a class="view-link" href="/viewer?modelUrl=${encodeURIComponent('/download/'+f.rel)}&productName=${encodeURIComponent(f.name)}" target="_blank">查看</a>`
          : '';
        return `
        <div class="file">
          <span><span class="nm">${f.name}</span><span class="sz">${fmtSize(f.size)}</span></span>
          <a href="/download/${encodeURIComponent(f.rel)}" download>下载</a>${viewLink}
        </div>`;
      }).join('')}
    </div>`).join('');
}

async function loadHistory(model){
  const area = document.getElementById('resultArea');
  area.innerHTML = '<div class="empty"><span class="spinner"></span>加载历史记录...</div>';
  try{
    const r = await fetch(`/api/build-info/${encodeURIComponent(model)}`);
    const data = await r.json();
    if(!data.ok){
      area.innerHTML = `<div class="err-msg">加载失败: ${data.error||'未知错误'}</div>`;
      return;
    }
    renderResult(data.result);
  }catch(e){
    area.innerHTML = `<div class="err-msg">请求异常: ${e}</div>`;
  }
}

function fmtSize(b){
  if(b>1048576) return (b/1048576).toFixed(2)+' MB';
  if(b>1024) return (b/1024).toFixed(1)+' KB';
  return b+' B';
}

loadOptions();
</script>
</body>
</html>
"""


# ===================== 路由 =====================
@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/viewer")
def viewer():
    """3D 模型查看器页面

    通过 URL 参数 modelUrl / productName 指定要加载的模型:
        /viewer?modelUrl=/download/250-E-H2K1-L100-D11/assembly.glb&productName=250-E-H2K1-L100-D11
    modelUrl 与 productName 均需 URL 编码。
    """
    return send_file(_VIEWER_HTML)


@app.route("/static/o3dv/<path:filename>")
def static_o3dv(filename):
    """提供 o3dv 渲染库及其依赖静态资源(o3dv.min.js / 字体 / 图标等)"""
    return send_from_directory(os.path.join(_STATIC_DIR, "o3dv"), filename)


@app.route("/api/options")
def api_options():
    """返回所有系列的选型选项 + 电机编号映射"""
    series_list = []
    for p in sorted(glob.glob(os.path.join(CONFIG_DIR, "*.json"))):
        name = os.path.splitext(os.path.basename(p))[0]
        try:
            with open(p, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            continue
        series_list.append({
            "name": name,
            "mount": sorted(cfg.get("mount", {}).keys()),
            "load": sorted(cfg.get("load", {}).keys()),
            "motor": list(cfg.get("motor", {}).keys()),
            "strokes": sorted(cfg.get("cylinder", {}).get("table", {}).keys(),
                              key=lambda s: int(s.replace("L", "")) if s.replace("L", "").isdigit() else 0),
        })
    motor_codes = [{"code": k, "name": v} for k, v in rb.MOTOR_CODES.items()]
    return jsonify({"series": series_list, "motor_codes": motor_codes})


@app.route("/api/build", methods=["POST"])
def api_build():
    """按选型生成装配体

    ★ STEP 导出说明:
      装配体 STEP 使用 XCAF 模式导出(rebuild_assembly.step3_export_assembly_step_xcaf),
      保留零件名称和装配体层次结构(PRODUCT + NEXT_ASSEMBLY_USAGE_OCCURRENCE)。
      SolidWorks 导入后可展开查看各零件,与 SW 原生导出效果一致。

      旧版导出(step3_export_assembly_step)使用 STEPControl_Writer + Compound,
      会丢失零件名称,SolidWorks 中显示为 "Open CASCADE STEP translator...",
      该函数已保留但不再在主流程中调用,仅供单零件/单面 STEP 导出或备用回退。
    """
    data = request.get_json(force=True) or {}
    model_code = (data.get("model_code") or "").strip()
    if not model_code:
        return jsonify({"ok": False, "error": "model_code 不能为空"}), 400
    motor = (data.get("motor") or "").strip() or None
    series = (data.get("series") or "").strip() or None
    try:
        with _build_lock:
            result = rb.build_assembly(model_code, motor=motor, series=series)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500
    # 路径转相对(便于前端下载)
    def rel(p):
        return os.path.relpath(p, OUT_DIR).replace("\\", "/") if p else None
    result["step_file"] = rel(result.get("step_path"))
    result["glb_file"] = rel(result.get("glb_path"))
    result["cylinder_file"] = rel(result.get("cylinder_path"))
    return jsonify({"ok": True, "result": result})


@app.route("/api/files")
def api_files():
    """列出 output 目录已生成文件(按型号子目录分组)"""
    groups = []
    if os.path.isdir(OUT_DIR):
        for dname in sorted(os.listdir(OUT_DIR)):
            dpath = os.path.join(OUT_DIR, dname)
            if not os.path.isdir(dpath):
                continue
            files = []
            has_info = False
            for fname in os.listdir(dpath):
                fp = os.path.join(dpath, fname)
                if os.path.isfile(fp):
                    st = os.stat(fp)
                    files.append({
                        "name": fname,
                        "rel": f"{dname}/{fname}",
                        "size": st.st_size,
                        "mtime": int(st.st_mtime),
                    })
                    if fname == "build_info.json":
                        has_info = True
            # 分组内文件按修改时间倒序(最新的在前)
            files.sort(key=lambda f: f["mtime"], reverse=True)
            if files:
                groups.append({"model": dname, "files": files, "has_info": has_info})
    # 按最新文件修改时间倒序(最近生成的排前面)
    groups.sort(key=lambda g: max(f["mtime"] for f in g["files"]), reverse=True)
    return jsonify({"groups": groups, "total": sum(len(g["files"]) for g in groups)})


@app.route("/api/build-info/<model_code>")
def api_build_info(model_code):
    """读取指定型号的构建元数据(build_info.json)"""
    info_path = os.path.join(OUT_DIR, model_code, "build_info.json")
    if not os.path.isfile(info_path):
        return jsonify({"ok": False, "error": "未找到构建记录"}), 404
    try:
        with open(info_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return jsonify({"ok": True, "result": data})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/download/<path:filename>")
def download(filename):
    """下载 output 目录文件"""
    return send_from_directory(OUT_DIR, filename, as_attachment=True)


# ===================== 工程图相关路由 =====================
@app.route("/drawing")
def drawing_editor():
    """工程图编辑器页面"""
    return send_file(_DRAWING_EDITOR_HTML)


@app.route("/api/drawing-views/<model_code>")
def api_drawing_views(model_code):
    """生成指定型号的 2D 工程图视图(主视/俯视/侧视/轴测)

    从 assembly.step 生成 HLR 投影,返回 JSON 格式的 2D 线框数据。
    """
    from core import drawing_engine
    step_path = os.path.join(OUT_DIR, model_code, "assembly.step")
    if not os.path.isfile(step_path):
        return jsonify({"ok": False, "error": f"未找到 STEP 文件: {model_code}/assembly.step"}), 404

    try:
        with _build_lock:
            result = drawing_engine.generate_drawing_views_fast(step_path)
        return jsonify({"ok": True, "result": result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/drawing-pdf", methods=["POST"])
def api_drawing_pdf():
    """将前端 SVG 数据转换为 PDF 导出

    请求体: {"svg": "<svg>...</svg>", "model": "250-E-H2K1-L100"}
    响应: PDF 文件下载
    """
    try:
        import io
        from reportlab.graphics import renderPDF
        from svglib.svglib import svg2rlg

        data = request.get_json()
        svg_str = data.get("svg", "")
        model = data.get("model", "untitled")

        # 将 SVG 字符串转为 reportlab drawing
        svg_io = io.StringIO(svg_str)
        drawing = svg2rlg(svg_io)

        if drawing is None:
            return jsonify({"ok": False, "error": "SVG 解析失败"}), 500

        # 渲染为 PDF
        pdf_buffer = io.BytesIO()
        renderPDF.drawToFile(drawing, pdf_buffer, "工程图_" + model)
        pdf_buffer.seek(0)

        return send_file(
            pdf_buffer,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"工程图_{model}.pdf"
        )
    except ImportError:
        return jsonify({"ok": False, "error": "缺少依赖: pip install svglib reportlab"}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/generate-drawing/<model_code>", methods=["POST"])
def api_generate_drawing(model_code):
    """为指定型号生成工程图 PDF

    请求体: {
        "stroke": 100,
        "bore_diameter": "250",
        "motor_power": "0.75",
        ...
    }
    响应: 生成的 PDF 文件下载
    """
    from drawing import drawing_generator
    
    step_path = os.path.join(OUT_DIR, model_code, "assembly.step")
    if not os.path.isfile(step_path):
        return jsonify({"ok": False, "error": f"未找到 STEP 文件: {model_code}/assembly.step"}), 404
    
    try:
        data = request.get_json() or {}
        
        # 构建参数
        params = {
            "model_code": model_code,
            "stroke": int(data.get("stroke", 100)),
            "bore_diameter": data.get("bore_diameter", "250"),
            "motor_power": data.get("motor_power", ""),
            "rated_speed": data.get("rated_speed", ""),
            "rated_torque": data.get("rated_torque", ""),
            "max_speed": data.get("max_speed", ""),
            "screw_model": data.get("screw_model", ""),
            "screw_lead": data.get("screw_lead", ""),
            "reduction_ratio": data.get("reduction_ratio", ""),
            "positioning_accuracy": data.get("positioning_accuracy", "±0.02"),
        }
        
        # 输出路径
        output_pdf = os.path.join(OUT_DIR, model_code, "drawing.pdf")
        
        # 生成工程图
        with _build_lock:
            result = drawing_generator.generate_drawing_pdf(step_path, output_pdf, params)
        
        if not result["success"]:
            return jsonify({"ok": False, "error": result.get("error", "生成失败")}), 500
        
        # 返回 PDF 文件
        return send_file(
            output_pdf,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"工程图_{model_code}.pdf"
        )
    
    except Exception as e:
        import traceback
        return jsonify({
            "ok": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ===================== DXF 工程图路由 =====================

@app.route("/api/drawing-dxf/<model_code>")
def api_drawing_dxf(model_code):
    """生成指定型号的 DXF 工程图文件

    流程: STEP → HLR投影 → 模板匹配 → 标注计算 → DXF导出
    返回 DXF 文件下载。
    """
    from drawing import dxf_exporter
    from drawing.rule_template import drawing_template
    from datetime import datetime

    step_path = os.path.join(OUT_DIR, model_code, "assembly.step")
    if not os.path.isfile(step_path):
        return jsonify({"ok": False, "error": f"未找到 STEP 文件: {model_code}/assembly.step"}), 404

    try:
        # 解析型号参数
        parts = model_code.split("-")
        series = parts[0] if parts else ""

        params = {
            "model_code": model_code,
            "series": series,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "scale": "2"
        }

        output_dxf = os.path.join(OUT_DIR, model_code, "drawing.dxf")

        with _build_lock:
            dxf_path, elapsed, unmatched = dxf_exporter.generate_dxf_from_step(
                step_path, output_dxf, params=params
            )

        return send_file(
            dxf_path,
            as_attachment=True,
            download_name=f"工程图_{model_code}.dxf"
        )

    except Exception as e:
        import traceback
        return jsonify({
            "ok": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@app.route("/api/drawing-data/<model_code>")
def api_drawing_data(model_code):
    """生成指定型号的工程图数据(JSON,含视图+标注+标题栏)

    供前端 cad-viewer 渲染或调试用。
    """
    from core import drawing_engine
    from drawing.rule_template import drawing_template
    from datetime import datetime

    step_path = os.path.join(OUT_DIR, model_code, "assembly.step")
    if not os.path.isfile(step_path):
        return jsonify({"ok": False, "error": f"未找到 STEP 文件: {model_code}/assembly.step"}), 404

    try:
        parts = model_code.split("-")
        series = parts[0] if parts else ""
        params = {
            "model_code": model_code,
            "series": series,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "scale": "2"
        }

        with _build_lock:
            views_data = drawing_engine.generate_drawing_views_raw(step_path)
            template = drawing_template.load_default_template()
            anchors = drawing_template.load_default_anchors()
            views_data["anchors"] = anchors
            drawing_data = drawing_template.apply_template(views_data, template, params)

        return jsonify({
            "ok": True,
            "drawing": drawing_data,
            "template": template,
            "anchors": anchors,
            "elapsed": views_data["elapsed"],
            "model_bbox": views_data["model_bbox"],
            "unmatched": drawing_data.get("unmatched", [])
        })

    except Exception as e:
        import traceback
        return jsonify({
            "ok": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ===================== 前端实例模板路由 =====================

# 前端编辑器"保存为模板"落盘目录(与规则式模板区分)
TEMPLATES_DIR = os.path.join(_PROJECT_ROOT, "data", "templates", "engineering")


def _template_identity(model_id):
    """模板身份 = 型号前三段(系列-连接-安装负载),后两段为系列内变量"""
    return "-".join(str(model_id).split("-")[:3])


@app.route("/api/drawing-template", methods=["POST"])
def api_save_drawing_template():
    """保存前端编辑器当前图纸为实例模板

    请求体即 buildDrawingDocument() 输出(sheet/model_id/views/annotations)。
    落盘 data/templates/engineering/<model_id>.json,并写入模板身份。
    """
    doc = request.get_json(silent=True)
    if not isinstance(doc, dict):
        return jsonify({"ok": False, "error": "请求体必须是 JSON 对象"}), 400
    model_id = doc.get("model_id")
    views = doc.get("views")
    if not model_id or not isinstance(model_id, str):
        return jsonify({"ok": False, "error": "缺少 model_id(请先导入模型)"}), 400
    if not views:
        return jsonify({"ok": False, "error": "views 为空(请先放置视图)"}), 400

    doc = dict(doc)
    doc["template_kind"] = "frontend-instance"
    doc["template_identity"] = _template_identity(model_id)
    doc["schema_version"] = 1

    os.makedirs(TEMPLATES_DIR, exist_ok=True)
    path = os.path.join(TEMPLATES_DIR, f"{model_id}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
    except OSError as e:
        return jsonify({"ok": False, "error": f"写入失败: {e}"}), 500
    return jsonify({"ok": True, "template_id": model_id,
                    "identity": doc["template_identity"], "path": path})


@app.route("/api/drawing-templates", methods=["GET"])
def api_list_drawing_templates():
    """列出全部前端实例模板(按身份分组信息一并返回)"""
    if not os.path.isdir(TEMPLATES_DIR):
        return jsonify({"ok": True, "templates": []})
    templates = []
    for name in sorted(os.listdir(TEMPLATES_DIR)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(TEMPLATES_DIR, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        templates.append({
            "template_id": doc.get("model_id"),
            "identity": doc.get("template_identity"),
            "view_count": len(doc.get("views", [])),
            "annotation_count": len(doc.get("annotations", [])),
            "file": name,
        })
    return jsonify({"ok": True, "templates": templates})


# ===================== 模板出图路由(导入模板 → 选型号 → 生成 → 下载) =====================

def _parse_uploaded_template():
    """解析上传的模板(multipart 的 file 字段,或 JSON 请求体)

    Returns:
        (doc, None) 成功;(None, error_response) 失败
    """
    if request.files:
        f = request.files.get("file")
        if f is None:
            return None, (jsonify({"ok": False, "error": "缺少 file 字段"}), 400)
        try:
            doc = json.loads(f.read().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            return None, (jsonify(
                {"ok": False, "error": f"模板不是合法 UTF-8 JSON: {e}"}), 400)
    else:
        doc = request.get_json(silent=True)

    if not isinstance(doc, dict):
        return None, (jsonify({"ok": False,
                               "error": "模板内容必须是 JSON 对象"}), 400)
    model_id = doc.get("model_id")
    if not model_id or not isinstance(model_id, str):
        return None, (jsonify({"ok": False,
                               "error": "模板缺少 model_id 字段"}), 400)
    if not doc.get("views"):
        return None, (jsonify({"ok": False, "error": "模板 views 为空"}), 400)
    return doc, None


def _save_template_doc(model_id, doc):
    """模板落盘 data/templates/engineering/<model_id>.json"""
    os.makedirs(TEMPLATES_DIR, exist_ok=True)
    with open(os.path.join(TEMPLATES_DIR, f"{model_id}.json"),
              "w", encoding="utf-8") as fp:
        json.dump(doc, fp, ensure_ascii=False, indent=2)


@app.route("/api/template-drawing/upload", methods=["POST"])
def api_upload_drawing_template():
    """上传前端导出的实例模板 JSON

    支持两种提交方式:
      1. multipart/form-data,字段 file(模板 .json 文件)
      2. application/json,请求体即模板文档
    落盘到 data/templates/engineering/<model_id>.json,并补全模板身份。
    """
    doc, err = _parse_uploaded_template()
    if err:
        return err

    model_id, views = doc["model_id"], doc["views"]
    doc = dict(doc)
    doc["template_kind"] = "frontend-instance"
    doc["template_identity"] = _template_identity(model_id)
    doc["schema_version"] = 1

    try:
        _save_template_doc(model_id, doc)
    except OSError as e:
        return jsonify({"ok": False, "error": f"写入失败: {e}"}), 500

    return jsonify({
        "ok": True,
        "template_id": model_id,
        "identity": doc["template_identity"],
        "view_count": len(views),
        "annotation_count": len(doc.get("annotations", [])),
    })


@app.route("/api/template-drawing/series-models")
def api_series_models():
    """列出与指定模板身份同系列、且已生成过模型的全部型号

    查询参数:
        identity  模板系列身份(型号前三段),或
        template_id  已保存模板的 model_id(二者给其一)
    """
    identity = request.args.get("identity", "").strip()
    template_id = request.args.get("template_id", "").strip()
    if not identity and template_id:
        identity = _template_identity(template_id)
    if not identity:
        return jsonify({"ok": False, "error": "缺少 identity 或 template_id"}), 400

    if not os.path.isdir(OUT_DIR):
        return jsonify({"ok": True, "identity": identity, "models": []})

    models = []
    for name in sorted(os.listdir(OUT_DIR)):
        model_dir = os.path.join(OUT_DIR, name)
        if not os.path.isdir(model_dir):
            continue
        if _template_identity(name) != identity:
            continue
        has_step = os.path.isfile(os.path.join(model_dir, "assembly.step"))
        has_brep = os.path.isfile(os.path.join(model_dir, "assembly.brep"))
        if not (has_step or has_brep):
            continue  # 无形状文件,无法出图
        models.append({
            "model_code": name,
            "has_pdf": os.path.isfile(
                os.path.join(model_dir, "drawing_frontend.pdf")),
        })
    return jsonify({"ok": True, "identity": identity, "models": models})


def _load_template_doc(template_id):
    """读取已保存的模板文档,返回 (template_doc, error_response)"""
    tpl_path = os.path.join(TEMPLATES_DIR, f"{template_id}.json")
    if not os.path.isfile(tpl_path):
        return None, (jsonify({
            "ok": False,
            "error": f"模板不存在: {template_id}(请先上传或保存模板)"}), 404)
    try:
        with open(tpl_path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except (OSError, json.JSONDecodeError) as e:
        return None, (jsonify({"ok": False,
                               "error": f"模板读取失败: {e}"}), 500)


def _reject_cross_series(models, tmpl_identity):
    """不同系列几何差异过大,共用模板无意义,返回被拒型号列表"""
    rejected = [m for m in models if _template_identity(m) != tmpl_identity]
    if not rejected:
        return None
    return jsonify({
        "ok": False,
        "error": f"以下型号与模板系列({tmpl_identity})不同: "
                 f"{', '.join(rejected)}",
        "rejected": rejected,
    }), 400


def _to_client_results(results):
    """出图结果转前端结构:PDF 绝对路径改相对项目根,供下载接口使用"""
    out = []
    for r in results:
        pdf_abs = r.get("pdf") or ""
        rel = os.path.relpath(pdf_abs, _PROJECT_ROOT).replace("\\", "/") \
            if pdf_abs else None
        out.append({
            "model_code": r.get("model_code"),
            "ok": bool(r.get("ok")),
            "error": r.get("error"),
            "pdf": rel,
            "elapsed": r.get("elapsed"),
            "dims": r.get("dims", []),
            "unmatched": r.get("unmatched", []),
        })
    return out


@app.route("/api/template-drawing/generate", methods=["POST"])
def api_generate_from_template():
    """用实例模板对选定型号批量生成工程图 PDF

    请求体:
        template_id  已保存模板的 model_id(必填)
        models       型号编码数组(必填,可多选)
    返回每个型号的出图结果(ok / pdf / 标注命中情况 / 失配原因)。
    """
    body = request.get_json(silent=True) or {}
    template_id = body.get("template_id")
    models = body.get("models") or []
    if not template_id:
        return jsonify({"ok": False, "error": "缺少 template_id"}), 400
    if not isinstance(models, list) or not models:
        return jsonify({"ok": False, "error": "models 必须是非空数组"}), 400

    template_doc, err = _load_template_doc(template_id)
    if err:
        return err

    tmpl_identity = template_doc.get("template_identity") or \
        _template_identity(template_doc.get("model_id", ""))
    err = _reject_cross_series(models, tmpl_identity)
    if err:
        return err

    # 校验通过后才加载出图管线:它顶层依赖 pythonOCC,
    # 提前 import 会让纯参数校验也背上 OCC 依赖
    from batch import batch_drawing as bd
    try:
        results = bd.run_frontend(models, template_doc, OUT_DIR)
    except Exception as e:
        return jsonify({"ok": False, "error": f"出图失败: {e}"}), 500

    return jsonify({
        "ok": True,
        "identity": tmpl_identity,
        "template_id": template_id,
        "results": _to_client_results(results),
    })


@app.route("/api/template-drawing/download/<path:relpath>")
def api_download_template_pdf(relpath):
    """下载生成的工程图 PDF(relpath 为相对项目根的路径)"""
    # 防目录穿越:规范化后必须仍在项目根内
    abs_path = os.path.abspath(os.path.join(_PROJECT_ROOT, relpath))
    if not abs_path.startswith(os.path.abspath(_PROJECT_ROOT) + os.sep):
        return jsonify({"ok": False, "error": "非法路径"}), 400
    if not os.path.isfile(abs_path):
        return jsonify({"ok": False, "error": "文件不存在"}), 404
    return send_file(abs_path, mimetype="application/pdf",
                     as_attachment=True,
                     download_name=os.path.basename(abs_path))


@app.route("/api/template-drawing/preview/<path:relpath>")
def api_preview_template_pdf(relpath):
    """在线预览生成的工程图 PDF(浏览器内嵌打开,非下载)"""
    abs_path = os.path.abspath(os.path.join(_PROJECT_ROOT, relpath))
    if not abs_path.startswith(os.path.abspath(_PROJECT_ROOT) + os.sep):
        return jsonify({"ok": False, "error": "非法路径"}), 400
    if not os.path.isfile(abs_path):
        return jsonify({"ok": False, "error": "文件不存在"}), 404
    return send_file(abs_path, mimetype="application/pdf")


# ===================== SolidWorks 风格视图面板路由 =====================

def _find_model_shape_path(model_code):
    """查找模型的形状文件路径(优先 STEP,回退 BRep 缓存)

    Returns:
        文件路径(str)或 None(都不存在)
    """
    model_dir = os.path.join(OUT_DIR, model_code)
    step_path = os.path.join(model_dir, "assembly.step")
    if os.path.isfile(step_path):
        return step_path
    brep_path = os.path.join(model_dir, "assembly.brep")
    if os.path.isfile(brep_path):
        return brep_path
    return None


@app.route("/api/drawing-view-palette/<model_code>")
def api_drawing_view_palette(model_code):
    """生成 SolidWorks 风格的视图调色板数据

    导入模型后调用,预生成 9 个标准视图(6 基本 + 3 轴测),
    每个视图包含 SVG 缩略图和归一化的边线数据(用于拖拽到画布)。

    支持 assembly.step 或 assembly.brep(缓存)文件。

    响应:
        {
            "ok": true,
            "views": {
                "front": {"label", "group", "thumbnail", "edges", "hidden_edges", "bbox", ...},
                "back": {...},
                ...
            },
            "model_bbox": {"width", "height", "depth"},
            "elapsed": float
        }
    """
    from core import drawing_engine

    shape_path = _find_model_shape_path(model_code)
    if not shape_path:
        return jsonify({"ok": False, "error": f"未找到模型文件(assembly.step 或 assembly.brep): {model_code}"}), 404

    try:
        with _build_lock:
            result = drawing_engine.generate_all_standard_views(shape_path)
        # 补充电机/减速机包络投影,供前端"电机包络"标注工具预览
        try:
            from drawing import anchor_resolver
            from drawing.dim import dim_envelope
            anchors = anchor_resolver.resolve_anchors(model_code)["anchors"]
            motor_envelope = {}
            gearbox_envelope = {}
            for view_name in result["views"]:
                env = dim_envelope.envelope_faces(anchors, view_name, body_id="motor.body")
                if env:
                    motor_envelope[view_name] = {
                        "orientation": env["orientation"],
                        "face_min": env["face_min"],
                        "face_max": env["face_max"],
                        "span_mm": env["span_mm"],
                        "outline": env["outline"],
                    }
                env2 = dim_envelope.gearbox_envelope_faces(anchors, view_name)
                if env2:
                    gearbox_envelope[view_name] = {
                        "orientation": env2["orientation"],
                        "face_min": env2["face_min"],
                        "face_max": env2["face_max"],
                        "span_mm": env2["span_mm"],
                        "outline": env2["outline"],
                    }
            result["motor_envelope"] = motor_envelope
            result["gearbox_envelope"] = gearbox_envelope
        except Exception:
            result["motor_envelope"] = {}
            result["gearbox_envelope"] = {}
        return jsonify({"ok": True, **result})
    except Exception as e:
        import traceback
        return jsonify({
            "ok": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@app.route("/api/drawing-view-single/<model_code>/<view_name>")
def api_drawing_view_single(model_code, view_name):
    """按需生成单个视图的投影数据(高分辨率版)

    用于用户拖拽视图到画布后,请求更高分辨率的边线数据。

    响应:
        {
            "ok": true,
            "view": {"view_name", "label", "visible", "hidden", "bbox", "seg_count"}
        }
    """
    from core import drawing_engine

    shape_path = _find_model_shape_path(model_code)
    if not shape_path:
        return jsonify({"ok": False, "error": f"未找到模型文件: {model_code}"}), 404

    try:
        with _build_lock:
            view = drawing_engine.generate_view_by_name(shape_path, view_name)
        if view is None:
            return jsonify({"ok": False, "error": f"无效的视图名: {view_name}"}), 400
        return jsonify({"ok": True, "view": view})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    os.makedirs(OUT_DIR, exist_ok=True)
    print("=" * 56)
    print("  装配体生成可视化面板")
    print("  浏览器打开: http://127.0.0.1:5001")
    print("  3D 查看器:   http://127.0.0.1:5001/viewer")
    print("  工程图编辑器: http://127.0.0.1:5001/drawing")
    print("=" * 56)
    # pythonOCC 非线程安全,用单线程串行处理请求
    app.run(host="127.0.0.1", port=5001, debug=False, threaded=False)
