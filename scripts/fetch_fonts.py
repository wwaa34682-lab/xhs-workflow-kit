#!/usr/bin/env python3
"""下载三款默认字体到 fonts/（都是 SIL Open Font License 1.1：免费、可商用、可嵌入图片；可再分发但不能单独售卖字体）。
本仓库不内置字体文件，避免仓库变大；运行一次即可：python scripts/fetch_fonts.py
下载失败时，按 fonts/README.md 里的链接手动下载，放进 fonts/ 目录。"""
import os, sys, urllib.request, zipfile, io
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C
D = os.path.join(C.KIT, 'fonts'); os.makedirs(D, exist_ok=True)
FONTS = [
    ('ZCOOLKuaiLe-Regular.ttf', 'https://github.com/google/fonts/raw/main/ofl/zcoolkuaile/ZCOOLKuaiLe-Regular.ttf', None),
    ('LXGWWenKai-Medium.ttf', 'https://github.com/lxgw/LxgwWenKai/releases/latest/download/LXGWWenKai-Medium.ttf', None),
    ('SmileySans-Oblique.ttf', 'https://github.com/atelier-anchor/smiley-sans/releases/download/v2.0.1/smiley-sans-v2.0.1.zip', 'SmileySans-Oblique.ttf'),
]
for name, url, member in FONTS:
    dst = os.path.join(D, name)
    if os.path.exists(dst): print('已有', name); continue
    try:
        data = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'xhs-workflow-kit'}), timeout=60).read()
        if member:
            z = zipfile.ZipFile(io.BytesIO(data)); data = z.read(next(n for n in z.namelist() if n.endswith(member)))
        open(dst, 'wb').write(data); print('下载完成', name, f'{len(data)//1024} KB')
    except Exception as e:
        print('下载失败', name, e, '→ 手动下载：', url, file=sys.stderr)
