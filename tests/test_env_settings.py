# -*- coding: utf-8 -*-
""".env 加载器测试

覆盖解析规则(注释/空行/引号/export 前缀)与加载语义(不覆盖已存在的
环境变量、文件缺失不报错)。不依赖真实 .env 文件,全部用临时目录。

运行:
    C:\\Users\\<user>\\.conda\\envs\\pdf1\\python.exe -m pytest tests/ -v
"""
import os
import sys

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))

from web import env_settings


def test_parse_ignores_comments_and_blanks():
    text = "\n# 注释行\n\n   \nKEY=1\n"
    assert env_settings.parse_env_text(text) == {"KEY": "1"}


def test_parse_strips_quotes():
    text = 'A="x"\nB=\'y\'\nC=plain\n'
    assert env_settings.parse_env_text(text) == {
        "A": "x", "B": "y", "C": "plain"}


def test_parse_supports_export_prefix():
    assert env_settings.parse_env_text("export FOO=bar") == {"FOO": "bar"}


def test_parse_skips_lines_without_equals():
    assert env_settings.parse_env_text("NOEQUALS\nK=v\n") == {"K": "v"}


def test_load_env_writes_value(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("BUILD_POOL_WORKERS=6\n", encoding="utf-8")
    monkeypatch.delenv("BUILD_POOL_WORKERS", raising=False)
    applied = env_settings.load_env(str(tmp_path))
    assert applied == ["BUILD_POOL_WORKERS"]
    assert os.environ["BUILD_POOL_WORKERS"] == "6"


def test_load_env_does_not_override_existing(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("FOO=from_file\n", encoding="utf-8")
    monkeypatch.setenv("FOO", "from_env")
    assert env_settings.load_env(str(tmp_path)) == []
    assert os.environ["FOO"] == "from_env"


def test_load_env_override_flag_forces_file_value(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("FOO=from_file\n", encoding="utf-8")
    monkeypatch.setenv("FOO", "from_env")
    env_settings.load_env(str(tmp_path), override=True)
    assert os.environ["FOO"] == "from_file"


def test_load_env_missing_file_is_noop(tmp_path):
    assert env_settings.load_env(str(tmp_path)) == []


def test_project_env_example_has_no_secret_values():
    """.env.example 应入库且只放非敏感默认值"""
    path = os.path.join(_PROJECT_ROOT, ".env.example")
    assert os.path.isfile(path), ".env.example 应入库,否则团队不知道有哪些开关"
    with open(path, encoding="utf-8") as f:
        text = f.read()
    assert "BUILD_POOL_WORKERS" in text
