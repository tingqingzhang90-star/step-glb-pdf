# -*- coding: utf-8 -*-
"""视图投影方向与模型主轴(Z)的换算 — 投影/重绑/包络共用的唯一方向源

HLR 用 gp_Ax2(origin, N=dir, Vx=dir×up) 定义投影面,边线的 mm 坐标就落在
该坐标系的 X/Y 轴上。凡是「某个视图里缸体长轴沿哪根屏幕轴」的问题,都从
这里的 dir/up 推算,不再按视图名各维护一张映射表:新增视图只登记一次,
所有消费方自动生效,漏登记也不再静默退化成错误投影。
"""
import math

# dir: 视线方向; up: 屏幕上方向参考(均为模型坐标,无需预先归一化)
VIEW_DIRECTIONS = {
    "front":           {"dir": (0, 0, 1),       "up": (0, 1, 0)},
    "back":            {"dir": (0, 0, -1),      "up": (0, 1, 0)},
    "left":            {"dir": (1, 0, 0),       "up": (0, 1, 0)},
    "right":           {"dir": (-1, 0, 0),      "up": (0, 1, 0)},
    "top":             {"dir": (0, -1, 0),      "up": (0, 0, -1)},
    "bottom":          {"dir": (0, 1, 0),       "up": (0, 0, 1)},
    "left_top":        {"dir": (0, 1, 0),       "up": (-1, 0, 0)},
    "isometric":       {"dir": (-1, -1, 1),     "up": (0, 0, 1)},
    "dimetric_left":   {"dir": (1, -1, 0.5),    "up": (0, 0, 1)},
    "dimetric_right":  {"dir": (-1, -1, -0.5),  "up": (0, 0, 1)},
}


def _unit(v):
    n = math.sqrt(sum(c * c for c in v))
    if n < 1e-9:
        raise ValueError("零向量不能作为投影方向")
    return tuple(c / n for c in v)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def view_screen_axes(view_name):
    """视图屏幕 x/y 轴在模型坐标下的单位向量(与 gp_Ax2 的 X/Y 一致)"""
    cfg = VIEW_DIRECTIONS.get(view_name)
    if not cfg:
        raise ValueError(f"未定义视图投影方向: {view_name}")
    n = _unit(cfg["dir"])
    x = _unit(_cross(n, cfg["up"]))       # Vx = dir × up
    y = _unit(_cross(n, x))              # ax2.Y = N × Vx
    return x, y


def axial_projection(view_name):
    """模型 +Z(缸体长轴) 落在哪根屏幕轴上

    Returns:
        (axis, sign): 如 ("x", 1.0); None 表示 +Z 垂直投影面(front/back),
        行程拉伸不改变 2D 位置,无需补偿。

    Raises:
        ValueError: 视图未定义,或 +Z 斜投影(轴测)——单轴补偿无法表达,
        必须显式报失配,不能静默跳过补偿后按旧坐标匹配。
    """
    x, y = view_screen_axes(view_name)
    cx, cy = x[2], y[2]
    if abs(cx) > 0.999 and abs(cy) < 0.001:
        return ("x", 1.0 if cx > 0 else -1.0)
    if abs(cy) > 0.999 and abs(cx) < 0.001:
        return ("y", 1.0 if cy > 0 else -1.0)
    if abs(cx) < 1e-3 and abs(cy) < 1e-3:
        return None
    raise ValueError(f"视图 {view_name} 的 +Z 为斜投影,不支持单轴补偿")
