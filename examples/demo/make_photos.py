"""生成 demo 用的占位“照片”（纯程序绘制的无人物静物场景，虚构，无版权问题）。"""
import os, numpy as np
from PIL import Image, ImageDraw, ImageFilter
D = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'photos'); os.makedirs(D, exist_ok=True)
rng = np.random.default_rng(1)
for i, (wall, floor, mat) in enumerate([((236, 222, 204), (196, 160, 122), (240, 106, 78)),
                                         ((214, 228, 222), (180, 150, 118), (47, 122, 107)),
                                         ((240, 230, 214), (170, 132, 100), (255, 200, 120))], 1):
    W, H = 1200, 1500; im = Image.new('RGB', (W, H), wall); d = ImageDraw.Draw(im)
    d.rectangle([0, int(H * .62), W, H], fill=floor)
    d.rectangle([760, 140, 1080, 620], fill=(255, 250, 238)); d.line([920, 140, 920, 620], fill=wall, width=12); d.line([760, 380, 1080, 380], fill=wall, width=12)
    d.polygon([(180, 1080), (980, 1080), (1100, 1380), (60, 1380)], fill=mat)
    d.ellipse([140, 760, 440, 1060], fill=(250, 240, 228)); d.rectangle([520, 900, 600, 1080], fill=(90, 70, 60))
    d.ellipse([490, 860, 630, 930], fill=(110, 160, 120))
    a = np.asarray(im, np.float32)
    yy, xx = np.mgrid[0:H, 0:W]; light = 1 + .18 * np.exp(-(((xx - 920) / 600) ** 2 + ((yy - 380) / 700) ** 2))
    a = np.clip(a * light[..., None] + rng.normal(0, 4, a.shape), 0, 255).astype(np.uint8)
    Image.fromarray(a).filter(ImageFilter.GaussianBlur(1.2)).save(f'{D}/demo_{i:02d}.jpg', quality=88)
print('ok', D)
