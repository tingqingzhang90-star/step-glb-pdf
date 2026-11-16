# -*- coding: utf-8 -*-
"""PDF 中文字体注册

STSong-Light(Adobe-GB1 CID 字体)没有 ø/Ø(U+00F8/U+00D8)字形,
直径标注渲染时符号会静默丢失。SimSun(simsun.ttc)同时覆盖 CJK 与
Latin-1 补充区,且同为宋体风格,优先注册;字体文件缺失(非 Windows
部署)时回退 STSong-Light,行为与旧版一致。
"""
import os

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont

_CN_FONT = "STSong-Light"
_FONT_READY = False
_SIMSUN = r"C:\Windows\Fonts\simsun.ttc"


def ensure_cn_font():
    """注册中文字体并返回字体名(进程内只注册一次)"""
    global _CN_FONT, _FONT_READY
    if _FONT_READY:
        return _CN_FONT
    if os.path.isfile(_SIMSUN):
        try:
            pdfmetrics.registerFont(TTFont("SimSun", _SIMSUN, subfontIndex=0))
            _CN_FONT = "SimSun"
        except Exception:
            pass
    if _CN_FONT == "STSong-Light":
        pdfmetrics.registerFont(UnicodeCIDFont(_CN_FONT))
    _FONT_READY = True
    return _CN_FONT
