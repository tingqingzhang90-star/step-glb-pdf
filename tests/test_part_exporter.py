# -*- coding: utf-8 -*-
"""零件导出流程测试

用假的 SW COM 对象替换 win32com,不启动 SolidWorks、不依赖真实装配体。
覆盖:装配体候选解析、共享件归类、导出统计与产物落盘。

运行:
    C:\\Users\\<user>\\.conda\\envs\\pdf1\\python.exe -m pytest tests/test_part_exporter.py -v
"""
import json
import os
import sys

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))

pytest.importorskip("win32com.client")

from core import part_exporter as pe  # noqa: E402
from core import paths  # noqa: E402


class _FakeXform:
    def __init__(self):
        self.ArrayData = [float(i) for i in range(16)]


class _FakeComp:
    def __init__(self, name, path):
        self.Name2 = name
        self.GetPathName = path
        self.IsSuppressed = False
        self.Transform2 = _FakeXform()


class _FakeExtension:
    def SaveAs(self, path, *args):
        with open(path, "w", encoding="utf-8") as f:
            f.write("fake step content")
        return True


class _FakeDoc:
    def __init__(self):
        self.Extension = _FakeExtension()


class _FakeAsm:
    def __init__(self, comps):
        self._comps = comps

    def GetComponents(self, _top_only):
        return self._comps


class _FakeSW:
    """只实现 part_exporter 用到的接口"""

    def __init__(self, comps):
        self._comps = comps
        self.Visible = True

    def OpenDoc6(self, path, doc_type, options, config, errors, warnings):
        return _FakeAsm(self._comps) if doc_type == pe.SW_DOC_ASSEMBLY else _FakeDoc()

    def SetUserPreferenceIntegerValue(self, _id, _value):
        return True

    def SetUserPreferenceToggle(self, _id, _value):
        return True

    def CloseDoc(self, _name):
        return True


def _install_fake_sw(monkeypatch, comps):
    monkeypatch.setattr(pe.pythoncom, "CoInitialize", lambda: None)
    monkeypatch.setattr(pe.pythoncom, "CoUninitialize", lambda: None)
    monkeypatch.setattr(pe.win32com.client, "Dispatch",
                        lambda _name: _FakeSW(comps))


def _use_tmp_library(monkeypatch, tmp_path, series="测试系列"):
    lib = tmp_path / "图库项目"
    (lib / series).mkdir(parents=True)
    asm = lib / series / "测试装配体.SLDASM"
    asm.write_text("", encoding="utf-8")
    monkeypatch.setattr(paths, "LIB_ROOT", str(lib))
    monkeypatch.setattr(paths, "SERIES_ROOT", str(tmp_path / "library" / "series"))
    monkeypatch.setattr(paths, "SHARED_PARTS_DIR", str(tmp_path / "library" / "shared"))
    return str(asm)


def test_resolve_assembly_picks_unique_candidate(monkeypatch, tmp_path):
    asm = _use_tmp_library(monkeypatch, tmp_path)
    assert pe.resolve_assembly("测试系列") == asm


def test_resolve_assembly_accepts_bare_filename(monkeypatch, tmp_path):
    asm = _use_tmp_library(monkeypatch, tmp_path)
    assert pe.resolve_assembly("测试系列", os.path.basename(asm)) == asm


def test_resolve_assembly_rejects_multiple_candidates(monkeypatch, tmp_path):
    _use_tmp_library(monkeypatch, tmp_path)
    extra = os.path.join(paths.LIB_ROOT, "测试系列", "备用装配体.SLDASM")
    with open(extra, "w", encoding="utf-8") as f:
        f.write("")
    with pytest.raises(ValueError):
        pe.resolve_assembly("测试系列")


def test_list_assemblies_skips_sw_lock_files(monkeypatch, tmp_path):
    _use_tmp_library(monkeypatch, tmp_path)
    lock = os.path.join(paths.LIB_ROOT, "测试系列", "~$测试装配体.SLDASM")
    with open(lock, "w", encoding="utf-8") as f:
        f.write("")
    assert len(pe.list_assemblies("测试系列")) == 1


def test_export_series_writes_parts_and_matrix(monkeypatch, tmp_path):
    part_a = tmp_path / "测试缸体.SLDPRT"
    part_b = tmp_path / "11kw.SLDPRT"
    for p in (part_a, part_b):
        p.write_text("", encoding="utf-8")
    comps = [_FakeComp("测试缸体-1", str(part_a)), _FakeComp("11kw-1", str(part_b))]
    _use_tmp_library(monkeypatch, tmp_path)
    _install_fake_sw(monkeypatch, comps)

    result = pe.export_series("测试系列")

    assert result["exported"] == 2
    assert result["components"] == 2
    # 共享件被移出系列目录
    assert os.path.isfile(os.path.join(paths.SHARED_PARTS_DIR, "11kw.step"))
    assert not os.path.isfile(os.path.join(paths.parts_dir("测试系列"), "11kw.step"))
    assert os.path.isfile(os.path.join(paths.parts_dir("测试系列"), "测试缸体.step"))

    with open(paths.transform_json("测试系列"), encoding="utf-8") as f:
        data = json.load(f)
    assert data["测试缸体-1"]["step_file"] == "测试缸体.step"
    assert data["测试缸体-1"]["transform_matrix"][15] == 15.0
    assert data["测试缸体-1"]["suppressed"] is False

    with open(paths.meta_json("测试系列"), encoding="utf-8") as f:
        meta = json.load(f)
    assert meta["series"] == "测试系列"
    assert meta["shared_parts"] == ["11kw.step"]


def test_shared_part_conflict_kept_in_series(monkeypatch, tmp_path):
    """同名共享件但体积不一致时不移动,避免不同系列的电机互相覆盖"""
    part = tmp_path / "11kw.SLDPRT"
    part.write_text("", encoding="utf-8")
    _use_tmp_library(monkeypatch, tmp_path)
    _install_fake_sw(monkeypatch, [_FakeComp("11kw-1", str(part))])
    os.makedirs(paths.SHARED_PARTS_DIR, exist_ok=True)
    with open(os.path.join(paths.SHARED_PARTS_DIR, "11kw.step"), "w",
              encoding="utf-8") as f:
        f.write("different size")

    pe.export_series("测试系列")

    assert os.path.isfile(os.path.join(paths.parts_dir("测试系列"), "11kw.step"))


def test_cli_main_passes_arguments(monkeypatch):
    captured = {}

    def _fake_export(series, assembly, overwrite, on_progress):
        captured.update(series=series, assembly=assembly, overwrite=overwrite)
        return {}

    monkeypatch.setattr(pe, "export_series", _fake_export)
    monkeypatch.setattr(sys, "argv", ["part_exporter.py", "250折返", "--overwrite"])
    pe.main()
    assert captured == {"series": "250折返", "assembly": None, "overwrite": True}


def test_export_series_reports_progress(monkeypatch, tmp_path):
    part = tmp_path / "测试缸体.SLDPRT"
    part.write_text("", encoding="utf-8")
    _use_tmp_library(monkeypatch, tmp_path)
    _install_fake_sw(monkeypatch, [_FakeComp("测试缸体-1", str(part))])

    events = []
    pe.export_series("测试系列", on_progress=lambda e, p: events.append(e))

    assert events[0] == "start"
    assert "component" in events
    assert events[-1] == "done"


class _FakeOpenPart:
    """模拟「已在本机 SolidWorks 中打开」的零件:路径与本机解析路径不同(设计机旧路径)"""

    def __init__(self, title):
        self.GetPathName = f"Z:\\设计机旧路径\\{title}.SLDPRT"
        self.Extension = _FakeExtension()


class _FakeSWAlreadyOpen:
    """OpenDoc6 对零件返回 None(等同 SW 错误码 65536),靠 GetDocuments 复用已打开文档"""

    def __init__(self, comps):
        self._comps = comps
        self.Visible = True

    def OpenDoc6(self, path, doc_type, _options, _config, _errors, _warnings):
        if doc_type == pe.SW_DOC_ASSEMBLY:
            return _FakeAsm(self._comps)
        return None

    def GetDocuments(self):
        return [_FakeOpenPart(os.path.splitext(os.path.basename(p))[0])
                for p in (c.GetPathName for c in self._comps)]

    def SetUserPreferenceIntegerValue(self, _id, _value):
        return True

    def SetUserPreferenceToggle(self, _id, _value):
        return True

    def CloseDoc(self, _name):
        return True


def _install_already_open_sw(monkeypatch, comps):
    monkeypatch.setattr(pe.pythoncom, "CoInitialize", lambda: None)
    monkeypatch.setattr(pe.pythoncom, "CoUninitialize", lambda: None)
    monkeypatch.setattr(pe.win32com.client, "Dispatch",
                        lambda _name: _FakeSWAlreadyOpen(comps))


def test_export_reuses_already_open_doc_by_title(monkeypatch, tmp_path):
    """零件已在 SW 中打开(路径不一致)时,按文件名复用而非判为失败"""
    part = tmp_path / "测试缸体.SLDPRT"
    part.write_text("", encoding="utf-8")
    _use_tmp_library(monkeypatch, tmp_path)
    _install_already_open_sw(monkeypatch, [_FakeComp("测试缸体-1", str(part))])

    result = pe.export_series("测试系列")

    assert result["exported"] == 1
    assert result.get("failed", 0) == 0
    assert os.path.isfile(os.path.join(paths.parts_dir("测试系列"), "测试缸体.step"))

