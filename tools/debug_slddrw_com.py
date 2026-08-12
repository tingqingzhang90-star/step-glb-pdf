# -*- coding: utf-8 -*-
"""诊断 SLDDRW COM 提取: 不吞异常, 打印每一步"""
import os
import sys
import pythoncom
import win32com.client

path = os.path.abspath(sys.argv[1] if len(sys.argv) > 1
                       else r"图库项目\250直连\YRJ250-H3K2-E.SLDDRW")

pythoncom.CoInitialize()
try:
    app = win32com.client.gencache.EnsureDispatch("SldWorks.Application")
    print("gencache EnsureDispatch OK")
except Exception as e:
    print("EnsureDispatch 失败:", e)
    app = win32com.client.Dispatch("SldWorks.Application")
app.Visible = True

print("SW 版本:", app.RevisionNumber)

errors = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
warnings = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
print("打开:", path)
doc = app.OpenDoc6(path, 3, 1, "", errors, warnings)
print("OpenDoc6 →", doc, "errors=", errors.value, "warnings=", warnings.value)

if doc is None:
    # 尝试已打开的文档
    doc = app.ActiveDoc
    print("ActiveDoc →", doc)

# 尝试转换到 DrawingDoc 接口(GetCurrentSheet/GetFirstView 在 IDrawingDoc 上)
try:
    ddoc = win32com.client.CastTo(doc, 'IDrawingDoc')
    print("CastTo IDrawingDoc OK:", ddoc)
    doc_for_drawing = ddoc
except Exception as e:
    print("CastTo 失败:", e)
    doc_for_drawing = doc

if doc is not None:
    def val(x):
        return x() if callable(x) else x
    print("标题:", val(doc.GetTitle))
    print("类型:", val(doc.GetType))
    try:
        names = val(doc.GetSheetNames)
        print("GetSheetNames →", names)
    except Exception as e:
        print("GetSheetNames 异常:", e)
    try:
        sheet = doc_for_drawing.IGetCurrentSheet()
        print("IGetCurrentSheet →", sheet)
        if sheet:
            print("  sheet name:", val(sheet.GetName))
            try:
                print("  props:", list(sheet.GetProperties2()))
            except Exception as e:
                try:
                    print("  props(v1):", list(sheet.GetProperties()))
                except Exception as e2:
                    print("  props 异常:", e, e2)
    except Exception as e:
        print("IGetCurrentSheet 异常:", e)
    try:
        v = doc_for_drawing.IGetFirstView()
        print("IGetFirstView →", v)
        while v is not None:
            name = val(v.Name)
            print("  view:", name, end=" ")
            try:
                print("| orientation:", v.GetOrientationName(), "| scale:", val(v.ScaleDecimal), end=" ")
                pos = v.Position
                print("| pos:", list(pos) if pos else None)
            except Exception as e:
                print("(err:", e, ")")
            v = v.GetNextView()
    except Exception as e:
        print("IGetFirstView 异常:", e)
