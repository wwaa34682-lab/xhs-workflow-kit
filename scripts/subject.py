"""程序化主体 + 油画质感（纯 numpy/Pillow；装了 opencv-contrib 时用 cv2.xphoto.oilPainting 效果更好）。
主体类型：sphere（球体，可选 dimples 凹坑纹=颗粒质感）、disc（扁平圆）、image（产品抠图）、none。
想用别的主体（产品抠图、插画）就在 layout 里写 subject.type: image + path，脚本会贴图并统一做油画质感。"""
import numpy as np
from PIL import Image, ImageDraw, ImageFilter


def mix(a, b, t):
    return tuple(a[i] * (1 - t) + b[i] * t for i in range(3))


def ramp(base):
    blk, wht = (25, 10, 5), (255, 250, 235)
    return np.array([mix(base, blk, .62), mix(base, blk, .3), base, mix(base, wht, .3), mix(base, wht, .62)], float)


def gradient(w, h, top, bottom):
    t = np.linspace(0, 1, h)[:, None, None]
    return (np.array(top, float) * (1 - t) + np.array(bottom, float) * t) * np.ones((h, w, 3))


def stroke_noise(w, h, n, rng, length=(40, 140), width=(4, 12), angle_sd=0.2, mask_fn=None, tangential=None):
    im = Image.new('L', (w, h), 128); d = ImageDraw.Draw(im)
    for _ in range(n):
        x, y = rng.integers(0, w), rng.integers(0, h)
        if tangential and (x - tangential[0]) ** 2 + (y - tangential[1]) ** 2 < tangential[2] ** 2:
            a = np.arctan2(y - tangential[1], x - tangential[0]) + np.pi / 2 + rng.normal(0, .35); L = rng.integers(18, 50)
        else:
            a = rng.normal(0, angle_sd); L = rng.integers(*length)
        d.line([(x, y), (x + L * np.cos(a), y + L * np.sin(a))], fill=int(rng.integers(40, 216)), width=int(rng.integers(*width)))
    a = np.asarray(im.filter(ImageFilter.GaussianBlur(1.0)), np.float32) - 128
    gx = np.zeros_like(a); gy = np.zeros_like(a)
    gx[:, 1:-1] = a[:, 2:] - a[:, :-2]; gy[1:-1] = a[2:] - a[:-2]
    return -gx * 0.05 - gy * 0.06


def painterly(arr, rng, strength=1.0, tangential=None):
    """arr: HxWx3 float RGB → 油画笔触感。"""
    h, w = arr.shape[:2]
    img = np.clip(arr, 0, 255).astype(np.uint8)
    try:
        import cv2
        img = cv2.cvtColor(cv2.xphoto.oilPainting(cv2.cvtColor(img, cv2.COLOR_RGB2BGR), 9, 1), cv2.COLOR_BGR2RGB)
    except Exception:
        img = np.asarray(Image.fromarray(img).filter(ImageFilter.ModeFilter(7)).filter(ImageFilter.SMOOTH_MORE))
    rel = stroke_noise(w, h, int(9000 * strength), rng, tangential=tangential) * 4 * strength
    return np.clip(img.astype(np.float32) + rel[..., None], 0, 255)


def background(w, h, spec, rng):
    t = spec.get('type', 'gradient')
    if t == 'image' and spec.get('path'):
        im = Image.open(spec['path']).convert('RGB'); r = max(w / im.width, h / im.height)   # 等比铺满后居中裁切，不拉伸
        im = im.resize((int(im.width * r + 1), int(im.height * r + 1)), Image.LANCZOS)
        im = im.crop(((im.width - w) // 2, (im.height - h) // 2, (im.width - w) // 2 + w, (im.height - h) // 2 + h))
        arr = np.asarray(im, np.float32)
    elif t == 'solid':
        arr = np.ones((h, w, 3)) * np.array(spec['color'], float)
    else:
        arr = gradient(w, h, spec['top'], spec['bottom'])
    tex = float(spec.get('texture', 0.6))
    if tex > 0:
        arr = arr + stroke_noise(w, h, int(2600 * tex), rng, width=(6, 18))[..., None] * 6 * tex
        if spec.get('painterly', True):
            arr = painterly(arr, rng, strength=tex * 0.6)
    return np.clip(arr, 0, 255)


def sphere(arr, spec, rng):
    """在 arr 上画一个带光影的球体；返回 (arr, mask)。"""
    h, w = arr.shape[:2]; cx, cy = spec.get('center', [w // 2, int(h * .74)]); R = spec.get('radius', int(w * .55))
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    nx, ny = (xx - cx) / R, (yy - cy) / R; rr = nx ** 2 + ny ** 2; inside = rr < 1
    nz = np.sqrt(np.clip(1 - rr, 0, 1)); P = np.stack([nx, ny, nz], -1)[inside]
    N = P.copy(); ao = np.ones(len(P))
    if spec.get('pattern', 'none') == 'dimples':
        n = int(spec.get('dimples', 420)); i = np.arange(n) + .5; phi = np.arccos(1 - 2 * i / n); th = np.pi * (1 + 5 ** .5) * i
        D = np.stack([np.cos(th) * np.sin(phi), np.sin(th) * np.sin(phi), np.cos(phi)], -1)
        a = .35; Rx = np.array([[1, 0, 0], [0, np.cos(a), -np.sin(a)], [0, np.sin(a), np.cos(a)]]); D = D @ Rx.T
        idx = np.empty(len(P), int)
        for s in range(0, len(P), 200000):
            idx[s:s + 200000] = np.argmax(P[s:s + 200000] @ D.T, 1)
        dc = D[idx]; dist = np.linalg.norm(P - dc, axis=1); r0 = 0.092 * (420 / n) ** .5
        u = np.clip(dist / r0, 0, 1.5); ind = u < 1
        tang = dc - P; tang -= (tang * P).sum(1, keepdims=True) * P
        tn = tang / (np.linalg.norm(tang, axis=1, keepdims=True) + 1e-6)
        N = P + np.where(ind, .36 * u, 0)[:, None] * tn; N /= np.linalg.norm(N, axis=1, keepdims=True)
        ao = np.where(ind, 1 - .10 * np.exp(-((u - .95) / .08) ** 2) - .03 * (1 - u), 1.0)
    Lk = np.array([-.55, -.62, .56]); Lk /= np.linalg.norm(Lk); Lf = np.array([.85, .15, .5]); Lf /= np.linalg.norm(Lf)
    sh = (np.clip(N @ Lk, 0, 1) * .62 + np.clip(N @ Lf, 0, 1) * .22 + .30) * ao
    Hh = Lk + np.array([0, 0, 1]); Hh /= np.linalg.norm(Hh); sp = np.clip(N @ Hh, 0, 1) ** 30
    cols = ramp(tuple(spec['color'])); stops = np.array([0, .35, .70, .95, 1.15])
    col = np.stack([np.interp(np.clip(sh, 0, 1.15), stops, cols[:, c]) for c in range(3)], -1) + 255 * sp[:, None] * .1
    out = arr.copy(); out[inside] = np.clip(col, 0, 255)
    m = np.asarray(Image.fromarray((inside * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.5)), np.float32)[..., None] / 255
    out = arr * (1 - m) + out * m
    if spec.get('painterly', True):
        out = painterly(out, rng, tangential=(cx, cy, R))
    return out, m[..., 0]


def disc(arr, spec, rng):
    h, w = arr.shape[:2]; cx, cy = spec.get('center', [w // 2, int(h * .74)]); R = spec.get('radius', int(w * .55))
    yy, xx = np.mgrid[0:h, 0:w]; m = (((xx - cx) ** 2 + (yy - cy) ** 2) < R * R).astype(np.float32)
    out = arr * (1 - m[..., None]) + np.array(spec['color'], float) * m[..., None]
    return (painterly(out, rng, tangential=(cx, cy, R)) if spec.get('painterly', True) else out), m


def image_subject(arr, spec, rng):
    h, w = arr.shape[:2]; im = Image.open(spec['path']).convert('RGBA')
    sw = int(spec.get('width', w * .9)); im = im.resize((sw, int(im.height * sw / im.width)), Image.LANCZOS)
    cx, cy = spec.get('center', [w // 2, int(h * .7)])
    layer = Image.new('RGBA', (w, h)); layer.paste(im, (int(cx - im.width / 2), int(cy - im.height / 2)), im)
    a = np.asarray(layer, np.float32); m = a[..., 3:] / 255
    out = arr * (1 - m) + a[..., :3] * m
    return (painterly(out, rng, strength=.6) if spec.get('painterly', False) else out), m[..., 0]


def draw_subject(arr, spec, rng):
    t = (spec or {}).get('type', 'none')
    if t == 'sphere': return sphere(arr, spec, rng)
    if t == 'disc': return disc(arr, spec, rng)
    if t == 'image': return image_subject(arr, spec, rng)
    return arr, np.zeros(arr.shape[:2], np.float32)
