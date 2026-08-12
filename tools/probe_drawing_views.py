# -*- coding: utf-8 -*-
import os
import sys
import pythoncom
import win32com.client

path = os.path.abspath(sys.argv[1])
pythoncom.CoInitialize()
app = win32com.client.Dispatch("SldWorks.Application")
app.Visible = True
spec = app.GetOpenDocSpec(path)
spec.DocumentType = 3
spec.Silent = True
spec.ReadOnly = True
spec.LoadModel = True
doc = app.OpenDoc7(spec)
print("doc type", type(doc))
print("title", doc.GetTitle)
print("sheet count", doc.GetSheetCount)
print("sheet names", doc.GetSheetNames)
import importlib
m = importlib.import_module('win32com.gen_py.83A33D31-27C5-11CE-BFD4-00400513BB57x0x32x0')
try:
    v = m.IView(doc._oleobj_.InvokeTypes(34, 0, 1, (9, 0), (),))
    print("first view", v)
    if v is not None:
        print("first name", v.GetName())
        n = v.GetNextView()
        print("next view", n)
except Exception as e:
    print("first view err", e)
try:
    s = m.ISheet(doc._oleobj_.InvokeTypes(70, 0, 1, (9, 0), (),))
    print("current sheet", s)
    print("sheet name", s.GetName())
except Exception as e:
    print("current sheet err", e)
print("active doc", app.ActiveDoc)

