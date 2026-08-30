# -*- coding: utf-8 -*-
"""SW COM 选型对比工具 — 在 SolidWorks 中切换选型(抑制/取消抑制)供肉眼比对

功能:
    1. Web 面板选型(复用 build_config 生成的配置 JSON)
    2. 每次重新打开装配体(避免上次抑制状态影响)
    3. 按选型参数抑制/取消抑制组件(不做 STEP 导出)
    4. 尝试通过方程式修改缸体 D1(可选)
    5. SW 窗口保持可见,用户直接在 SW 中查看比对

运行:
    conda run -n pdf1 python src/sw_compare_server.py
访问: http://127.0.0.1:5001
"""
import os
import sys
import re
import json
import time
import threading

# 复用 rebuild_assembly 的选型解析逻辑(本文件位于 src/web/,需把 src 加入 sys.path)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.rebuild_assembly import (
    parse_model_code, resolve_visibility, load_config,
    compute_cylinder_scale, MOTOR_CODES, _KEY_RE,
)

from flask import Flask, request, jsonify, Response

# ---------- 配置 ----------
# 本文件位于 src/web/,需上溯三级: web → src → 项目根
_PROJECT_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
CONFIG_DIR = os.path.join(_PROJECT_ROOT, "data", "configs")
LIB_ROOT = os.path.join(_PROJECT_ROOT, "图库项目")
# 装配体根目录(图库项目下按系列名分子目录)
ASSEMBLY_LIB = os.path.join(os.path.dirname(_PROJECT_ROOT), "pdf修改", "图库项目")
if not os.path.isdir(ASSEMBLY_LIB):
    ASSEMBLY_LIB = LIB_ROOT  # 回退

# SW COM 常量
SW_DOC_ASSEMBLY = 2
SW_OPEN_SILENT = 1
SW_SUPPRESSED = 0    # swComponentSuppressed
SW_RESOLVED = 2      # swComponentResolved

app = Flask(__name__)
_lock = threading.Lock()  # COM 非线程安全,串行执行


# ---------- SW COM 操作 ----------
def _find_assembly(series_name):
    """按约定查找系列装配体: <ASSEMBLY_LIB>/<series>/<series>装配体.SLDASM"""
    cand = os.path.join(ASSEMBLY_LIB, series_name, f"{series_name}装配体.SLDASM")
    if os.path.exists(cand):
        return cand
    # 回退:目录下第一个不含 ce/_parallel 的 SLDASM
    d = os.path.join(ASSEMBLY_LIB, series_name)
    if os.path.isdir(d):
        for f in sorted(os.listdir(d)):
            if f.upper().endswith(".SLDASM") and "ce" not in f and "_parallel" not in f:
                return os.path.join(d, f)
    return cand  # 返回约定路径(后续报错)


def _make_byref_int():
    import pythoncom
    import win32com.client
    return win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)


def _set_cylinder_d1(part_doc, d1_mm, part_label=""):
    """通过零件尺寸参数修改缸体 D1(参考 PythonServer/toolkit/cylinder_d1.py)

    1. 优先尝试硬编码 D1@凸台-拉伸1(160 系列)
    2. 失败后枚举零件参数找第一个 D1@*
    返回 (是否成功, 消息)
    """
    label = f" ({part_label})" if part_label else ""
    # 1) 优先历史硬编码特征名
    try:
        param = part_doc.Parameter("D1@凸台-拉伸1")
        param.SetSystemValue3(d1_mm / 1000.0, 2, "")  # 2=米制,值用米
        return True, f"D1={d1_mm}mm @ 凸台-拉伸1{label}"
    except Exception:
        pass
    # 2) 退化:扫描所有参数找 D1@*
    try:
        cnt = int(part_doc.GetParameterCount())
        for i in range(cnt):
            try:
                p = part_doc.GetParameter(i)
                name = str(p.Name)
                if name.startswith("D1@"):
                    p.SetSystemValue3(d1_mm / 1000.0, 2, "")
                    return True, f"D1={d1_mm}mm @ {name}{label}"
            except Exception:
                continue
    except Exception:
        pass
    # 诊断:dump 零件前 20 个参数名,便于排查"为什么找不到 D1"
    msg = f"未找到 D1@ 尺寸参数{label}(需手动改缸体尺寸)"
    try:
        sample = []
        if hasattr(part_doc, "GetParameterCount"):
            cnt2 = int(part_doc.GetParameterCount())
            for i in range(min(cnt2, 20)):
                try:
                    sample.append(str(part_doc.GetParameter(i).Name))
                except Exception:
                    pass
        if sample:
            msg += f"; param_sample={sample}"
    except Exception:
        pass
    return False, msg


def _get_model_doc2_robust(sw_app, comp):
    """获取组件的零件文档,带轻量化 fallback(参考 sw_com.Component.get_model_doc2)。

    1. 优先 comp.GetModelDoc2()
    2. 轻量化返回 None 时:SetComponentState(FULLY_RESOLVED) → GetPathName
       → OpenDoc6 重新打开零件文档返回。

    背景:SolidWorks 默认以轻量化方式打开装配体组件,此时 GetModelDoc2()
    返回 null/不完整对象,对其调用 Parameter() 会报 DISP_E_MEMBERNOTFOUND
    "找不到成员"。必须强制 fully-resolve 后用 OpenDoc6 重开零件,才能拿到
    完整的 IPartDoc,使 Parameter()/GetParameter() 可用。

    返回:零件文档 IDispatch 或 None。
    """
    SW_DOC_PART = 1
    SW_OPEN_SILENT = 1
    SW_COMPONENT_FULLY_RESOLVED = 2
    # 1) 优先 GetModelDoc2
    try:
        md = comp.GetModelDoc2
        doc = md() if callable(md) else md
        if doc is not None:
            return doc
    except Exception:
        pass
    # 2) 轻量化 fallback:强制 fully-resolve,再用 OpenDoc6 重开
    try:
        comp.SetComponentState(SW_COMPONENT_FULLY_RESOLVED)
    except Exception:
        pass
    try:
        gp = comp.GetPathName
        path = gp() if callable(gp) else gp
    except Exception:
        path = None
    if not path:
        return None
    try:
        errors = _make_byref_int()
        warnings = _make_byref_int()
        opened = sw_app.OpenDoc6(path, SW_DOC_PART, SW_OPEN_SILENT,
                                 "", errors, warnings)
        return opened
    except Exception:
        return None


def sw_apply_selection(model_code, motor=None, series_name=None):
    """在 SW 中重新打开装配体并应用选型(抑制/取消抑制)

    每次重新打开文件,确保干净状态。
    返回结果字典。
    """
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    try:
        # 1. 解析型号
        params = parse_model_code(model_code)
        mount = params["mount"]
        load = params["load"]
        motor_name = params["motor"] or motor or "11kw电机"
        if series_name is None:
            series_name = f"{params['series']}直连"

        # 2. 加载配置 + 计算显隐
        config = load_config(series_name)
        visibility = resolve_visibility(config, mount, load, motor_name)

        # 3. 缸体 D1 计算(用于方程式/提示)
        cyl_info = compute_cylinder_scale(config, params["stroke"])
        d1 = cyl_info[1] if cyl_info else None
        scale = cyl_info[2] if cyl_info else None

        # 4. 连接 SW
        sw = win32com.client.Dispatch("SldWorks.Application")
        sw.Visible = True

        asm_path = _find_assembly(series_name)
        asm_name = os.path.basename(asm_path)

        # 5. 关闭已打开的装配体(每次重新打开)
        try:
            sw.CloseDoc(asm_name)
        except Exception:
            pass
        time.sleep(0.5)

        # 6. 重新打开装配体
        errors = _make_byref_int()
        warnings = _make_byref_int()
        model = sw.OpenDoc6(asm_path, SW_DOC_ASSEMBLY, SW_OPEN_SILENT, "", errors, warnings)
        if model is None:
            return {"ok": False, "error": f"打开装配体失败(errors={errors.value})"}

        # 7. 解决所有轻量化组件(参考 jdg_controller apply_config)
        #    组件处于轻量化状态时,GetModelDoc2() 返回的零件文档不完整,
        #    调用 Parameter() 会报 DISP_E_MEMBERNOTFOUND "找不到成员"。
        #    必须先把轻量化组件全部 resolve,后续才能修改缸体 D1。
        try:
            model.ResolveAllLightWeightComponents(False)
        except Exception:
            pass

        cyl_msg = ""
        cyl_part_name = config.get("cylinder_part")

        # 8. 获取所有组件
        components = model.GetComponents(False)
        count = len(components) if components else 0

        # ★ FIX: 必须先 EditAssembly() 进入编辑装配体模式,
        # 否则 SetSuppression2 会静默失败(状态不翻转)
        try:
            model.EditAssembly()
        except Exception:
            pass

        details = []
        suppressed_count = 0
        resolved_count = 0
        skipped_count = 0
        error_count = 0

        for i in range(count):
            comp = components[i]
            try:
                raw_name = comp.Name2
            except Exception:
                raw_name = f"<组件{i}>"
            # Name2 可能返回 "250前盖-1" 或 "250前盖-1@装配体"
            name = str(raw_name).split("@")[0]
            m = _KEY_RE.match(name)
            base = m.group(1) if m else name

            should_show = visibility.get(base, True)

            try:
                # ★ FIX: 用 SetSuppression2 而非 SetSuppressionState(后者静默失败)
                if should_show:
                    comp.SetSuppression2(SW_RESOLVED)
                    resolved_count += 1
                    state = "显示"
                else:
                    comp.SetSuppression2(SW_SUPPRESSED)
                    suppressed_count += 1
                    state = "抑制"
            except Exception as e:
                error_count += 1
                state = f"错误: {e}"

            details.append({"name": name, "base": base, "state": state})

        # ★ FIX: SetSuppression2 后必须 EditRebuild3() 才能生效
        # (H11 fix: SetSuppression2 silently no-op without EditRebuild3)
        try:
            model.EditRebuild3()
        except Exception:
            pass

        # 9. 缸体 D1 修改(参考 jdg_controller apply_config 的顺序)
        #    必须在 抑制循环 + EditRebuild3 之后做:此时缸体组件已 resolved。
        #    用 _get_model_doc2_robust 取零件文档(带轻量化 fallback):
        #    轻量化组件 GetModelDoc2 返回 null → Parameter 报"找不到成员",
        #    robust 版会 SetComponentState(FULLY_RESOLVED)+OpenDoc6 重开零件。
        if d1 and cyl_part_name:
            try:
                for c in components:
                    cn = str(c.Name2 or "").split("@")[0]
                    if cn == cyl_part_name or cn.startswith(cyl_part_name + "-"):
                        part_doc = _get_model_doc2_robust(sw, c)
                        if part_doc is not None:
                            ok, cyl_msg = _set_cylinder_d1(part_doc, d1, cn)
                        break
            except Exception as e:
                cyl_msg = f"缸体 D1 修改异常: {e}"

        # 10. 强制重建 + 刷新窗口
        try:
            model.ForceRebuild3(False)
        except Exception:
            pass

        # 不关闭装配体,让用户在 SW 中查看
        return {
            "ok": True,
            "model_code": model_code,
            "motor": motor_name,
            "series": series_name,
            "assembly": asm_path,
            "d1": d1,
            "scale": round(scale, 3) if scale else None,
            "cyl_msg": cyl_msg,
            "total": count,
            "resolved": resolved_count,
            "suppressed": suppressed_count,
            "errors": error_count,
            "details": details,
            "elapsed_hint": "SW 窗口已打开,请切换到 SolidWorks 查看装配体",
        }
    except Exception as e:
        import traceback
        return {"ok": False, "error": str(e), "trace": traceback.format_exc()}
    finally:
        pythoncom.CoUninitialize()


# ---------- API ----------
@app.route("/api/options")
def api_options():
    """扫描配置目录返回各系列的选型选项"""
    options = []
    if os.path.isdir(CONFIG_DIR):
        for fn in sorted(os.listdir(CONFIG_DIR)):
            if not fn.endswith(".json"):
                continue
            series = fn[:-5]
            try:
                with open(os.path.join(CONFIG_DIR, fn), "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                options.append({
                    "series": series,
                    "mounts": list(cfg.get("mount", {}).keys()),
                    "loads": list(cfg.get("load", {}).keys()),
                    "motors": list(cfg.get("motor", {}).keys()),
                    "strokes": list(cfg.get("cylinder", {}).get("table", {}).keys()),
                })
            except Exception:
                pass
    return jsonify({"options": options})


@app.route("/api/sw-apply", methods=["POST"])
def api_sw_apply():
    """在 SW 中切换选型"""
    body = request.get_json(force=True)
    model_code = body.get("model_code", "").strip()
    motor = body.get("motor")
    series = body.get("series")

    if not model_code:
        return jsonify({"ok": False, "error": "缺少 model_code"}), 400

    with _lock:
        result = sw_apply_selection(model_code, motor, series)
    return jsonify(result)


# ---------- 前端页面 ----------
PAGE_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SW 选型对比面板</title>
<style>
:root{--bg:#0f1115;--card:#181b21;--border:#2a2e37;--txt:#e4e6eb;--txt2:#9aa0a8;
      --accent:#58a6ff;--green:#3fb950;--red:#f85149;--yellow:#d29922;--code:#1e2228}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,'Segoe UI',Roboto,sans-serif;background:var(--bg);
     color:var(--txt);padding:20px;max-width:1100px;margin:0 auto;font-size:14px}
h1{font-size:20px;margin-bottom:4px}
h2{font-size:15px;margin:18px 0 10px;color:var(--accent);border-bottom:1px solid var(--border);padding-bottom:6px}
.sub{color:var(--txt2);font-size:12px;margin-bottom:16px}
.card{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:16px;margin-bottom:16px}
.form-row{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:10px}
.field{flex:1;min-width:140px}
.field label{display:block;font-size:12px;color:var(--txt2);margin-bottom:4px}
.field select,.field input{width:100%;padding:7px 9px;background:var(--code);border:1px solid var(--border);
  border-radius:5px;color:var(--txt);font-size:13px}
.field select:focus,.field input:focus{outline:none;border-color:var(--accent)}
.preview{background:var(--code);border:1px solid var(--border);border-radius:5px;padding:10px 14px;
         font-family:'Consolas',monospace;font-size:14px;margin:10px 0}
.preview .mc{color:var(--green);font-weight:600}
.preview .d1{color:var(--yellow);font-size:12px;margin-left:12px}
.btn{padding:9px 20px;background:var(--accent);color:#fff;border:none;border-radius:5px;
     font-size:14px;font-weight:600;cursor:pointer;width:100%}
.btn:hover{opacity:.9}
.btn:disabled{opacity:.5;cursor:wait}
.result{margin-top:12px}
.stat{display:inline-block;background:var(--code);border:1px solid var(--border);border-radius:5px;
      padding:6px 14px;margin-right:8px;margin-bottom:6px;font-size:13px}
.stat .n{font-weight:700;color:var(--accent)}
.stat.ok .n{color:var(--green)}
.stat.bad .n{color:var(--red)}
table{width:100%;border-collapse:collapse;margin-top:10px;font-size:13px}
th,td{padding:6px 10px;text-align:left;border-bottom:1px solid var(--border)}
th{color:var(--txt2);font-weight:600;font-size:12px}
tr:hover td{background:var(--code)}
.tag{display:inline-block;padding:1px 8px;border-radius:3px;font-size:11px;font-weight:600}
.tag.on{background:rgba(63,185,80,.15);color:var(--green)}
.tag.off{background:rgba(248,81,73,.15);color:var(--red)}
.tag.err{background:rgba(210,153,34,.15);color:var(--yellow)}
.hint{background:rgba(88,166,255,.08);border:1px solid rgba(88,166,255,.3);border-radius:5px;
      padding:8px 12px;font-size:12px;color:var(--accent);margin-top:10px}
.err-box{background:rgba(248,81,73,.08);border:1px solid rgba(248,81,73,.3);border-radius:5px;
         padding:10px;color:var(--red);font-size:13px;white-space:pre-wrap;margin-top:10px}
</style>
</head>
<body>
<h1>SW 选型对比面板</h1>
<div class="sub">在 SolidWorks 中切换选型(抑制/取消抑制),与自研方案比对 · 每次重新打开装配体</div>

<div class="card">
  <h2 style="margin-top:0">选型参数</h2>
  <div class="form-row">
    <div class="field"><label>系列</label><select id="series"></select></div>
    <div class="field"><label>连接类型</label><select id="connType">
      <option value="E">E - 直连</option><option value="F">F - 折返</option>
    </select></div>
    <div class="field"><label>电机编号</label><select id="motorCode"></select></div>
  </div>
  <div class="form-row">
    <div class="field"><label>安装方式</label><select id="mount"></select></div>
    <div class="field"><label>负载连接</label><select id="load"></select></div>
    <div class="field"><label>行程</label><select id="stroke"></select></div>
  </div>
  <div class="preview" id="preview"></div>
  <button class="btn" id="btnApply" onclick="doApply()">在 SolidWorks 中切换选型</button>
</div>

<div class="card result" id="resultBox" style="display:none">
  <h2 style="margin-top:0">SW 操作结果</h2>
  <div id="resultBody"></div>
</div>

<script>
const MOTOR_OPTS = [
  {v:'D11',  t:'D11 - 11kw电机'},
  {v:'D55',  t:'D55 - 5.5KW电机'},
  {v:'D55B', t:'D55B - 5.5KW刹车电机'},
  {v:'D75',  t:'D75 - 7.5kw电机'},
  {v:'D75B', t:'D75B - 7.5kw电机刹车'},
  {v:'',     t:'不编入型号(--motor 回退)'},
];
let OPTS = [];

async function init(){
  // 电机选项
  document.getElementById('motorCode').innerHTML =
    MOTOR_OPTS.map(o=>`<option value="${o.v}">${o.t}</option>`).join('');

  const r = await fetch('/api/options');
  const data = await r.json();
  OPTS = data.options;
  if(!OPTS.length){ alert('未找到配置,请先运行 build_config.py'); return; }

  const sel = document.getElementById('series');
  sel.innerHTML = OPTS.map(o=>`<option value="${o.series}">${o.series}</option>`).join('');
  sel.onchange = () => fillOpts(sel.value);
  fillOpts(OPTS[0].series);
  updatePreview();

  ['connType','motorCode','mount','load','stroke'].forEach(id=>{
    document.getElementById(id).onchange = updatePreview;
  });
}

function fillOpts(series){
  const o = OPTS.find(x=>x.series===series);
  if(!o) return;
  document.getElementById('mount').innerHTML = o.mounts.map(m=>`<option>${m}</option>`).join('');
  document.getElementById('load').innerHTML = o.loads.map(l=>`<option>${l}</option>`).join('');
  document.getElementById('stroke').innerHTML = o.strokes.map(s=>`<option>${s}</option>`).join('');
  updatePreview();
}

function getMotorName(code){
  const m = {D11:'11kw电机',D55:'5.5KW电机',D55B:'5.5KW刹车电机',D75:'7.5kw电机',D75B:'7.5kw电机刹车'};
  return m[code] || '';
}

function updatePreview(){
  const series = document.getElementById('series').value;
  const conn = document.getElementById('connType').value;
  const mc = document.getElementById('motorCode').value;
  const mount = document.getElementById('mount').value;
  const load = document.getElementById('load').value;
  const stroke = document.getElementById('stroke').value;

  // 型号: 系列-类型-H*K*-行程[-电机]
  let code = `${series.split('直连')[0]}-${conn}-${mount}${load}-${stroke}`;
  if(mc) code += `-${mc}`;

  // D1 预览: stroke 数字 + 340
  const sm = stroke.match(/L?(\d+)/);
  const d1 = sm ? (parseInt(sm[1]) + 340) : null;

  document.getElementById('preview').innerHTML =
    `型号: <span class="mc">${code}</span>` +
    (d1 ? `<span class="d1">D1 = ${d1} mm (stroke+340)</span>` : '');
}

async function doApply(){
  const btn = document.getElementById('btnApply');
  btn.disabled = true; btn.textContent = '正在 SW 中操作...';
  const box = document.getElementById('resultBox');
  const body = document.getElementById('resultBody');
  box.style.display = 'block';
  body.innerHTML = '<div class="hint">正在连接 SolidWorks 并切换选型,请稍候...</div>';

  const series = document.getElementById('series').value;
  const conn = document.getElementById('connType').value;
  const mc = document.getElementById('motorCode').value;
  const mount = document.getElementById('mount').value;
  const load = document.getElementById('load').value;
  const stroke = document.getElementById('stroke').value;
  let code = `${series.split('直连')[0]}-${conn}-${mount}${load}-${stroke}`;
  if(mc) code += `-${mc}`;

  try{
    const r = await fetch('/api/sw-apply',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body: JSON.stringify({model_code:code, motor:getMotorName(mc), series:series})
    });
    const data = await r.json();
    renderResult(data);
  }catch(e){
    body.innerHTML = `<div class="err-box">请求失败: ${e}</div>`;
  }finally{
    btn.disabled = false; btn.textContent = '在 SolidWorks 中切换选型';
  }
}

function renderResult(d){
  const body = document.getElementById('resultBody');
  if(!d.ok){
    body.innerHTML = `<div class="err-box">${d.error||'未知错误'}${d.trace?'\n\n'+d.trace:''}</div>`;
    return;
  }
  let html = '';
  html += `<div class="stat ok">显示 <span class="n">${d.resolved}</span></div>`;
  html += `<div class="stat bad">抑制 <span class="n">${d.suppressed}</span></div>`;
  html += `<div class="stat">总计 <span class="n">${d.total}</span></div>`;
  if(d.errors>0) html += `<div class="stat bad">错误 <span class="n">${d.errors}</span></div>`;
  if(d.d1) html += `<div class="stat">D1 <span class="n">${d.d1}</span> mm</div>`;
  html += `<div class="hint">${d.elapsed_hint}</div>`;
  if(d.cyl_msg) html += `<div class="hint">缸体 D1: ${d.cyl_msg}</div>`;

  // 详情表
  html += `<table><thead><tr><th>#</th><th>组件名</th><th>基础名</th><th>状态</th></tr></thead><tbody>`;
  d.details.forEach((it,i)=>{
    let cls = it.state==='显示'?'on':(it.state==='抑制'?'off':'err');
    html += `<tr><td>${i+1}</td><td>${it.name}</td><td>${it.base}</td>`+
            `<td><span class="tag ${cls}">${it.state}</span></td></tr>`;
  });
  html += `</tbody></table>`;
  body.innerHTML = html;
}

init();
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return Response(PAGE_HTML, mimetype="text/html")


if __name__ == "__main__":
    print("SW 选型对比面板: http://127.0.0.1:5002")
    app.run(host="127.0.0.1", port=5002, debug=False, threaded=True)
