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

# 确保能 import 同目录模块
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from flask import (Flask, request, jsonify, send_from_directory,
                   send_file, render_template_string)

import rebuild_assembly as rb

_PROJECT_ROOT = os.path.dirname(_HERE)
OUT_DIR = rb.OUT_DIR
CONFIG_DIR = rb.CONFIG_DIR
# 3D 查看器相关路径(viewer.html 与 o3dv 静态资源均位于 src/ 下)
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
    import drawing_engine
    step_path = os.path.join(OUT_DIR, model_code, "assembly.step")
    if not os.path.isfile(step_path):
        return jsonify({"ok": False, "error": f"未找到 STEP 文件: {model_code}/assembly.step"}), 404

    try:
        with _build_lock:
            result = drawing_engine.generate_drawing_views(step_path)
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
