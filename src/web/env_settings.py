# -*- coding: utf-8 -*-
"""读取项目根 .env,把键值写入 os.environ

不引入 python-dotenv:本项目只需要"读一个 KEY=VALUE 文件",装第三方库
带来的依赖与 requirements.txt 维护成本远大于这三十行代码。

约定:
  * 已存在的环境变量优先,.env 不覆盖(命令行/系统变量可随时覆盖 .env)
  * # 开头与空行忽略;值两端的引号剥掉;允许 export 前缀
"""
import os


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def parse_env_text(text: str) -> dict[str, str]:
    """解析 .env 文本,返回 {key: value}(不做任何环境写入,便于测试)"""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        out[key] = _strip_quotes(value.strip())
    return out


def load_env(project_root: str, filename: str = ".env",
             override: bool = False) -> list[str]:
    """加载 .env 到 os.environ,返回实际写入的键

    Args:
        project_root: 项目根目录(.env 所在位置)
        filename: 文件名,传 ".env.example" 之类便于测试
        override: True 时用 .env 覆盖已存在的环境变量(默认不覆盖)

    Returns:
        list[str]: 实际写入的键名
    """
    path = os.path.join(project_root, filename)
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        pairs = parse_env_text(f.read())
    applied = []
    for key, value in pairs.items():
        if not override and key in os.environ:
            continue
        os.environ[key] = value
        applied.append(key)
    return applied
