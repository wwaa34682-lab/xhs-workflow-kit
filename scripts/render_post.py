#!/usr/bin/env python3
"""第 5 步 出图：按“模板改编”参数（config/layout.yaml）+ 稿件内容（drafts/<ID>/pages.yaml）渲染首图和内页。

用法
  python scripts/render_post.py --config config/brand.yaml --layout config/layout.yaml --draft data/drafts/D001
  python scripts/render_post.py ... --only cover          # 只出首图
  python scripts/render_post.py ... --variant B           # 用 layout 里 variants.B 覆盖配色（出 A/B 套系）

- layout.yaml = 用户给的参考图拆出来的版式参数（背景、主体、涂鸦、路线节点、文字槽位和样式），见 config/layout.example.yaml。
- pages.yaml = 这一篇的文字和照片（首图各槽位文字 + 内页列表）。文字里可以用 {brand.name}、{offer.0.price_text}、
  {locations_count} 引用 brand.yaml；**双星号** 包住的部分用数字字体+强调样式。
- brand.yaml 里没确认的字段会以【待业务确认】原样上图并在终端提示——不要发布带这个标记的图。
输出：<draft>/out[_<variant>]/P01.png … Pnn.png + preview.png

参考图闸门（硬规则）：必须先登记参考图才出图——data/refs/<稿件ID>/ 里至少 1 张参考图，并且 layout.yaml 的
reference.breakdown（版式/字体/调色/主体/装饰/文字位置）和 reference.kept / changed 都已填写（见 templates/参考图拆解清单.md）。
没有参考图时只能加 --no-reference-confirmed（用户看过“审美会非常差”的警告并二次确认后），这会记进评审回流库，评审时再次提醒补参考图。
"""
import argparse, copy, math, os, random, re, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C
import subject as SUB

MISSING = []
REF_KEYS = ['版式', '字体', '调色', '主体', '装饰', '文字位置']
IMG_EXT = ('.jpg', '.jpeg', '.png', '.webp')


def reference_problems(lay, refs_dir):
    """返回参考图登记缺什么（空列表 = 已登记）。"""
    probs = []
    imgs = [f for f in os.listdir(refs_dir) if f.lower().endswith(IMG_EXT)] if os.path.isdir(refs_dir) else []
    if not imgs: probs.append(f'{refs_dir} 里没有参考图')
    ref = lay.get('reference') or {}; bd = ref.get('breakdown') or {}
    bad = lambda v: C.is_unknown(v) or C.TODO in str(v)
    miss = [k for k in REF_KEYS if bad(bd.get(k))] + [k for k in ('kept', 'changed') if bad(ref.get(k))]
    if miss: probs.append('layout.yaml 的参考图拆解没填完：' + '、'.join(miss))
    return probs


def clamp_price(lay, root):
    """风格锁 SL-G14（价格不是点击钩子）生效时，首图价格强调字号最多为正文的 1.15 倍。"""
    rows = C.read_csv(os.path.join(root, 'tables', '风格锁.csv'))
    if not any(r.get('规则ID') == 'SL-G14' and r.get('状态', '').startswith('生效') for r in rows): return
    for nm, sl in ((lay.get('cover') or {}).get('slots') or {}).items():
        size = sl.get('size', 40); emph = sl.get('emph_size')
        if nm == 'offer' and emph and emph > size * 1.15:
            sl['emph_size'] = round(size * 1.15)
            print(f'[风格锁 SL-G14] 首图价格强调字号 {emph} → {sl["emph_size"]}（价格不当点击钩子）。确实要放大，请先让专家改这条规则', file=sys.stderr)


def log_no_reference(root, draft_id):
    p = C.data_paths(root)
    if not os.path.isdir(p['tables']):
        print('（没有资产表，无参考图确认未能写入评审回流库）', file=sys.stderr); return
    rows = C.load_table(p, '评审回流库')
    if any(r.get('稿件ID') == draft_id and r.get('问题类型') == '缺参考图' for r in rows): return
    import datetime
    n = sum(1 for r in rows if r.get('稿件ID') == draft_id) + 1
    rows.append({'回流ID': f'RV-{draft_id}-{n:02d}', '来源': '出图·无参考图', '稿件ID': draft_id, '评审日期': datetime.date.today().isoformat(),
                 '结论': '无参考图·用户已二次确认', '问题位置': '全部', '问题类型': '缺参考图',
                 '专家原话': '', '修改建议': '评审时再次请用户提供参考图，拿到后按「给参考图，做针对性修改」重做',
                 '回写目标': '', '是否已回写': '不需要', '备注': '用户已看过“没有参考图做出来的图片审美会非常差”的警告并二次确认'})
    C.save_table(p, '评审回流库', rows); print(f'已记录：{draft_id} 无参考图出图（评审回流库 RV-{draft_id}-{n:02d}）', file=sys.stderr)


def deep_merge(a, b):
    out = copy.deepcopy(a)
    for k, v in (b or {}).items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


class R:
    def __init__(self, cfg, lay, base_dir):
        self.cfg, self.lay, self.base = cfg, lay, base_dir
        self.W, self.H = lay.get('canvas', [1080, 1440]); self.S = 2
        self.pal = {k: self.color(v, {}) for k, v in (lay.get('palette') or {}).items()}
        self.pal = {k: self.color(v, self.pal) for k, v in (lay.get('palette') or {}).items()}

    # ---------------- helpers
    def color(self, v, pal=None):
        pal = self.pal if pal is None else pal
        if isinstance(v, str) and v.startswith('@'):
            k = v[1:]
            if k in pal: return pal[k]
            return C.hex2rgb(C.get(self.cfg, f'brand.colors.{k}'), (128, 128, 128))
        return C.hex2rgb(v, (128, 128, 128))

    def fill(self, s):
        def rep(m):
            k = m.group(1)
            if k == 'locations_count':
                return str(len(self.locations()))
            v = C.get(self.cfg, k)
            if C.is_unknown(v):
                MISSING.append(k); return C.UNKNOWN
            return str(v)
        return re.sub(r'\{([\w.]+)\}', rep, str(s))

    def locations(self):
        locs = self.cfg.get('locations') or []
        return [l.get('short') or l.get('name') if isinstance(l, dict) else str(l) for l in locs if l]

    def path(self, p):
        if not p: return None
        p = os.path.expanduser(str(p))
        root = os.path.dirname(os.path.dirname(os.path.abspath(self.base)))   # <data>，稿件目录的上两级
        for base in (self.base, root, os.path.dirname(root), os.getcwd(), C.KIT):
            q = p if os.path.isabs(p) else os.path.join(base, p)
            if os.path.exists(q): return q
        return None

    part_styles = {}   # 内页渲染时 = inner.styles（覆盖顶层 styles 的同名样式）

    def style(self, name):
        st = dict((self.lay.get('styles') or {}).get(name or 'plain', {}))
        st.update((self.part_styles or {}).get(name or 'plain', {}) or {})
        return dict(fill=self.color(st.get('fill', '@ink')), stroke=int(st.get('stroke_width', 0)),
                    stroke_fill=self.color(st.get('stroke', '@paper')), shadow=bool(st.get('shadow', False)),
                    shadow_color=self.color(st.get('shadow_color', '#000000')), shadow_alpha=float(st.get('shadow_alpha', .38)))

    # ---------------- text with outline + shadow
    def runs(self, text, slot):
        parts = re.split(r'(\*\*.+?\*\*)', self.fill(text)); out = []
        for p in parts:
            if not p: continue
            if p.startswith('**'):
                out.append((p[2:-2], C.font(self.cfg, slot.get('emph_font', 'number'), slot.get('emph_size', slot.get('size', 40) * 1.5)),
                            self.style(slot.get('emph_style', 'emphasis'))))
            else:
                out.append((p, C.font(self.cfg, slot.get('font', 'body'), slot.get('size', 40)), self.style(slot.get('style', 'plain'))))
        return out

    def draw_slot(self, img, text, slot):
        if text is None or str(text).strip() == '': return
        lines = str(text).split('\n'); y = slot.get('y', 100); lh = slot.get('line_height', slot.get('size', 40) * 1.35)
        for ln in lines:
            rs = self.runs(ln, slot); d = ImageDraw.Draw(img)
            tot = sum(d.textlength(t, font=f) for t, f, _ in rs)
            maxw = slot.get('max_width', self.W - 80)
            if tot > maxw:   # 太长就整行等比缩小，不出画面
                k = maxw / tot; sl2 = dict(slot, size=int(slot.get('size', 40) * k))
                if slot.get('emph_size'): sl2['emph_size'] = int(slot['emph_size'] * k)
                rs = self.runs(ln, sl2); tot = sum(d.textlength(t, font=f) for t, f, _ in rs)
                print(f'[出图] 文字「{self.fill(ln)[:12]}…」太长，已缩小到 {int(k * 100)}%', file=sys.stderr)
            al = slot.get('align', 'center'); x = slot.get('x', self.W / 2)
            x0 = x - tot / 2 if al == 'center' else (x - tot if al == 'right' else x)
            base = y + max(f.size for _, f, _ in rs) * .82
            for t, f, st in rs:
                self.text(img, (x0, base), t, f, st, anchor='ls'); x0 += d.textlength(t, font=f)
            y += lh

    def text(self, img, xy, t, f, st, anchor='la'):
        if st['shadow']:
            lay = Image.new('RGBA', img.size, (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
            d.text((xy[0] + 3, xy[1] + 5), t, font=f, fill=st['shadow_color'] + (255,), anchor=anchor,
                   stroke_width=st['stroke'], stroke_fill=st['shadow_color'] + (255,))
            a = lay.split()[3].filter(ImageFilter.GaussianBlur(4)).point(lambda v: int(v * st['shadow_alpha']))
            sh = Image.new('RGBA', img.size, st['shadow_color'] + (0,)); sh.putalpha(a); img.alpha_composite(sh)
        ImageDraw.Draw(img).text(xy, t, font=f, fill=st['fill'], anchor=anchor, stroke_width=st['stroke'],
                                 stroke_fill=st['stroke_fill'] if st['stroke'] else None)

    # ---------------- canvas
    def bg_spec(self, spec):
        s = dict(spec or {'type': 'gradient', 'top': '@bg_top', 'bottom': '@bg_bottom'})
        for k in ('top', 'bottom', 'color'):
            if k in s: s[k] = self.color(s[k])
        if s.get('path'): s['path'] = self.path(s['path'])
        return s

    def base_canvas(self, part, rng, with_subject):
        spec = self.lay.get(part, {}) or {}
        bg = self.bg_spec(spec.get('background') or self.lay.get('cover', {}).get('background'))
        if bg.get('type') == 'image' and not bg.get('path'):
            print(f'[出图] {part} 的背景照片没找到（{(spec.get("background") or {}).get("path")}），先用纯色渐变底；放好自有实拍后重出', file=sys.stderr)
            bg.setdefault('top', self.color('@primary')); bg.setdefault('bottom', self.color('@dark'))
        arr = SUB.background(self.W, self.H, bg, rng)
        mask = np.zeros((self.H, self.W), np.float32)
        if with_subject and spec.get('subject'):
            sj = dict(spec['subject']); sj['color'] = self.color(sj.get('color', '@subject'))
            if sj.get('path'): sj['path'] = self.path(sj['path'])
            if sj.get('type') == 'image' and not sj.get('path'):
                print(f'[出图] 产品抠图没找到（{spec["subject"].get("path")}），这版先不画主体；放好透明底 PNG 后重出', file=sys.stderr)
            else:
                arr, mask = SUB.draw_subject(arr, sj, rng)
            self.subject_mask = mask
        return Image.fromarray(arr.astype(np.uint8)).convert('RGBA'), mask

    # ---------------- doodles
    def doodles(self, img, spec, seed):
        if not spec or not spec.get('enabled', True): return
        S, W = self.S, self.W; ov = Image.new('RGBA', (W * S, self.H * S)); d = ImageDraw.Draw(ov)
        col = self.color(spec.get('color', '@doodle')) + (255,); rnd = random.Random(seed)

        def hand(pts, w=4, jit=1.0):
            q = [(x * S + rnd.uniform(-jit, jit) * S, y * S + rnd.uniform(-jit, jit) * S) for x, y in pts]
            d.line(q, fill=col, width=int(w * S), joint='curve')
        def star(x, y, r): hand([(x + (r if i % 2 == 0 else r * .45) * math.cos(math.radians(-90 + 36 * i)), y + (r if i % 2 == 0 else r * .45) * math.sin(math.radians(-90 + 36 * i))) for i in range(11)], 3, .5)
        def sparkle(x, y, r): hand([(x - r, y), (x + r, y)], 3, .3); hand([(x, y - r), (x, y + r)], 3, .3)
        def cloud(x, y, r):
            for dx, rr_ in ((-r, .8), (0, 1.1), (r, .8)):
                hand([(x + dx + rr_ * r * .6 * math.cos(math.radians(a)), y + rr_ * r * .6 * math.sin(math.radians(a))) for a in range(180, 361, 15)], 3, .3)
            hand([(x - r * 1.5, y), (x + r * 1.5, y)], 3, .3)
        def heart(x, y, r): hand([(x + r * 16 * math.sin(t) ** 3 / 16, y - r * (13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)) / 16) for t in np.linspace(0, 2 * math.pi, 40)], 3, .2)
        def swirl(x, y, r): hand([(x + r * (t / 12) * math.cos(t), y + r * (t / 12) * math.sin(t)) for t in np.linspace(0, 12, 50)], 3, .2)
        kinds = {'star': star, 'sparkle': sparkle, 'cloud': cloud, 'heart': heart, 'swirl': swirl}
        items = spec.get('items', ['star', 'sparkle', 'cloud', 'star', 'sparkle', 'heart', 'swirl', 'sparkle'])
        zones = spec.get('zones', [[40, 40, W - 40, 210]])
        for i, k in enumerate(items):
            z = zones[i % len(zones)]
            kinds.get(k, sparkle)(rnd.uniform(z[0], z[2]), rnd.uniform(z[1], z[3]), rnd.uniform(10, 20) * (1.6 if k == 'cloud' else 1))
        img.alpha_composite(ov.resize(img.size, Image.LANCZOS))

    # ---------------- route through locations
    def route(self, img, spec):
        if not spec or not spec.get('enabled', False): return
        names = self.locations()
        if not names:
            MISSING.append('locations'); names = [C.UNKNOWN]
        mx = spec.get('max_nodes', 8)
        if len(names) > mx: names = names[:mx - 1] + [f'等{len(names)}家']
        n = len(names); m = spec.get('x_margin', 92); y0 = spec.get('y', 1135); amp = spec.get('amplitude', 48)
        if n == 1 and spec.get('single', 'pin') == 'pin':
            return self.pin(img, spec, names[0], y0)
        self.check_route_collision(spec, y0, amp)
        P = [(m + (self.W - 2 * m) * (i / (n - 1) if n > 1 else .5), y0 + (-amp if i % 2 == 0 else amp)) for i in range(n)]
        S = self.S; ov = Image.new('RGBA', (self.W * S, self.H * S)); d = ImageDraw.Draw(ov)
        cv = catmull(P) if n > 1 else P
        lw = spec.get('width', 20)
        d.line([(x * S + 3 * S, y * S + 5 * S) for x, y in cv], fill=(40, 20, 10, 90), width=(lw + 10) * S, joint='curve')
        d.line([(x * S, y * S) for x, y in cv], fill=self.color(spec.get('edge', '@paper')) + (255,), width=(lw + 10) * S, joint='curve')
        d.line([(x * S, y * S) for x, y in cv], fill=self.color(spec.get('line', '@highlight')) + (255,), width=lw * S, joint='curve')
        for x, y in P:
            d.ellipse([(x - 12) * S, (y - 12) * S, (x + 12) * S, (y + 12) * S], fill=self.color('@paper') + (255,),
                      outline=self.color(spec.get('dot', '@ink')) + (255,), width=4 * S)
        img.alpha_composite(ov.resize(img.size, Image.LANCZOS))
        st = self.style(spec.get('label_style', 'on_subject'))
        fN = C.font(self.cfg, 'number', spec.get('number_size', 36)); fL = C.font(self.cfg, 'body', spec.get('label_size', 31))
        d = ImageDraw.Draw(img)
        for i, ((x, y), nm) in enumerate(zip(P, names)):
            ty = y - 104 if (i % 2 == 0 or spec.get('labels') == 'up') else y + 32
            num = f'{i + 1:02d}'; bw = max(d.textlength(num, font=fN), d.textlength(nm, font=fL))
            x0 = min(max(x - bw / 2, 24), self.W - 24 - bw)
            if spec.get('number', True): self.text(img, (x0, ty), num, fN, st)
            self.text(img, (x0, ty + 46), nm, fL, st)

    def pin(self, img, spec, name, y0):
        """只有 1 家店：画一个定位针 + 店名，不画孤立的 01 节点。"""
        S = self.S; ov = Image.new('RGBA', (self.W * S, self.H * S)); d = ImageDraw.Draw(ov)
        x, y = self.W / 2, y0; r = 26; col = self.color(spec.get('line', '@highlight')) + (255,); edge = self.color('@paper') + (255,)
        d.polygon([((x - r * .8) * S, (y - r * .6) * S), ((x + r * .8) * S, (y - r * .6) * S), (x * S, (y + r * 1.4) * S)], fill=col)
        d.ellipse([(x - r) * S, (y - r * 2) * S, (x + r) * S, y * S], fill=col, outline=edge, width=4 * S)
        d.ellipse([(x - r * .38) * S, (y - r * 1.38) * S, (x + r * .38) * S, (y - r * .62) * S], fill=edge)
        img.alpha_composite(ov.resize(img.size, Image.LANCZOS))
        st = self.style(spec.get('label_style', 'on_subject')); fL = C.font(self.cfg, 'body', spec.get('label_size', 34))
        tw = ImageDraw.Draw(img).textlength(name, font=fL); self.text(img, (x - tw / 2, y + 50), name, fL, st)

    def check_route_collision(self, spec, y0, amp):
        top, bot = y0 - amp - 110, y0 + amp + 90
        for nm, sl in ((self.lay.get('cover') or {}).get('slots') or {}).items():
            sy = sl.get('y', 0); h = sl.get('size', 40) * 1.3
            if sy < bot and sy + h > top:
                print(f'⚠ 出图：路线（y≈{top:.0f}–{bot:.0f}）和文字槽「{nm}」（y={sy}）可能重叠，请调整 route.y 或该槽位的 y', file=sys.stderr)
        m = getattr(self, 'subject_mask', None)
        if m is not None and m.size and m[int(max(0, top)):int(min(self.H, bot))].mean() > 0.3 and not spec.get('over_subject_ok'):
            print('⚠ 出图：路线压在主体上（专家常见意见“像地铁图”）。如果参考图就是这样，写 route.over_subject_ok: true；否则下移 route.y 或缩小主体', file=sys.stderr)

    # ---------------- pages
    def cover(self, page, seed):
        rng = np.random.default_rng(seed); img, _ = self.base_canvas('cover', rng, True)
        cv = self.lay.get('cover', {})
        self.doodles(img, cv.get('doodles'), seed); self.route(img, cv.get('route'))
        for name, slot in (cv.get('slots') or {}).items():
            self.draw_slot(img, page.get(name, slot.get('default')), slot)
        return img

    def photo(self, p, size, label):
        q = self.path(p)
        if q:
            im = Image.open(q).convert('RGB'); tw, th = size; r = max(tw / im.width, th / im.height)
            im = im.resize((int(im.width * r + 1), int(im.height * r + 1)), Image.LANCZOS)
            return im.crop(((im.width - tw) // 2, (im.height - th) // 2, (im.width - tw) // 2 + tw, (im.height - th) // 2 + th))
        im = Image.new('RGB', size, (236, 232, 222)); d = ImageDraw.Draw(im)
        for x in range(-size[1], size[0], 36): d.line([(x, 0), (x + size[1], size[1])], fill=(222, 216, 204), width=10)
        f = C.font(self.cfg, 'body', 34)
        for i, ln in enumerate(C.wrap_text(d, f'放自有实拍：{label or p or "照片"}', f, size[0] - 80)):
            d.text((size[0] / 2, size[1] / 2 - 30 + i * 46), ln, font=f, fill=(120, 112, 100), anchor='mm')
        if p: print(f'[照片] 没找到 {p}，用占位图（发布前换成自有实拍）', file=sys.stderr)
        return im

    def framed(self, im, frame, angle):
        if frame == 'polaroid':
            pad, bottom = 26, 110; c = Image.new('RGB', (im.width + 2 * pad, im.height + pad + bottom), (255, 253, 248)); c.paste(im, (pad, pad))
        elif frame == 'rounded':
            c = im; pad = 0
        else:
            return im.convert('RGBA')
        c = c.convert('RGBA')
        if frame == 'rounded':
            m = Image.new('L', c.size, 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, c.width, c.height], 36, fill=255); c.putalpha(m)
        return c.rotate(angle, resample=Image.BICUBIC, expand=True)

    def inner(self, page, seed, idx):
        rng = np.random.default_rng(seed + idx); spec = self.lay.get('inner', {}) or {}
        self.part_styles = spec.get('styles') or {}
        img, _ = self.base_canvas('inner', rng, False); self.doodles(img, spec.get('doodles'), seed + idx)
        photos = page.get('photos') or ([page['photo']] if page.get('photo') else [None])
        frame = page.get('frame', spec.get('frame', 'polaroid')); box = spec.get('photo_box', [90, 300, 990, 1180])
        n = len(photos); rnd = random.Random(seed + idx)
        for i, p in enumerate(photos[:3]):
            if n == 1:
                w_, h_ = box[2] - box[0] - 60, box[3] - box[1] - 140; cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
            else:
                w_, h_ = int((box[2] - box[0]) * .5), int((box[3] - box[1]) * .4)
                cx = box[0] + (box[2] - box[0]) * [.34, .68, .44][i]; cy = box[1] + (box[3] - box[1]) * [.24, .46, .68][i]
            fr = self.framed(self.photo(p, (int(w_), int(h_)), page.get('photo_label')), frame, rnd.uniform(-4, 4) if frame == 'polaroid' else 0)
            sh = Image.new('RGBA', fr.size, (0, 0, 0, 0)); sh.putalpha(fr.split()[3].point(lambda v: int(v * .35)))
            sh = sh.filter(ImageFilter.GaussianBlur(10))
            img.alpha_composite(sh, (int(cx - fr.width / 2 + 6), int(cy - fr.height / 2 + 12)))
            img.alpha_composite(fr, (int(cx - fr.width / 2), int(cy - fr.height / 2)))
        for name, slot in (spec.get('slots') or {}).items():
            self.draw_slot(img, page.get(name, slot.get('default')), slot)
        self.part_styles = {}
        return img


def apply_page_overrides(lay, pages, variant=None):
    """首图照片 / 产品抠图按稿件走：pages.yaml 顶层 cover_photo、cover_subject（路径相对稿件目录），
    以及 variants.<版本>.cover_photo / cover_subject。这样做第二篇不用改全局 layout.yaml，重出旧稿也不会串图。"""
    cv = lay.setdefault('cover', {})
    pv = ((pages.get('variants') or {}).get(variant) or {}) if variant else {}
    lay_v = ((lay.get('_variant_spec') or {}).get('cover') or {})
    photo = pv.get('cover_photo') or (None if variant and lay_v.get('background') else pages.get('cover_photo'))
    subj = pv.get('cover_subject') or (None if variant and lay_v.get('subject') else pages.get('cover_subject'))
    if photo:
        bg = dict(cv.get('background') or {}); bg.update(type='image', path=photo); cv['background'] = bg
    if subj:
        sj = dict(cv.get('subject') or {})
        if sj.get('type') in (None, 'none', 'sphere', 'disc'): sj.update(width=sj.get('width', 820), center=sj.get('center', [540, 900]))
        sj.update(type='image', path=subj); cv['subject'] = sj
    return lay


def needs_photo(lay):
    """这个版式要用户自己的照片吗？返回 'cover_photo' / 'cover_subject' / None。"""
    cv = lay.get('cover') or {}
    if (cv.get('background') or {}).get('type') == 'image': return 'cover_photo'
    if (cv.get('subject') or {}).get('type') == 'image': return 'cover_subject'
    return None


def catmull(ps, n=30):
    ps = [(ps[0][0] - 60, ps[0][1] + 70)] + ps + [(ps[-1][0] + 40, ps[-1][1] - 30)]; out = []
    for i in range(1, len(ps) - 2):
        p0, p1, p2, p3 = ps[i - 1], ps[i], ps[i + 1], ps[i + 2]
        for t in [j / n for j in range(n)]:
            t2, t3 = t * t, t * t * t
            out.append(tuple(.5 * (2 * p1[k] + (-p0[k] + p2[k]) * t + (2 * p0[k] - 5 * p1[k] + 4 * p2[k] - p3[k]) * t2 + (-p0[k] + 3 * p1[k] - 3 * p2[k] + p3[k]) * t3) for k in (0, 1)))
    out.append(ps[-2]); return out


def preview(files, out):
    ims = [Image.open(f).convert('RGB') for f in files]; tw = 360; th = int(tw * ims[0].height / ims[0].width)
    sheet = Image.new('RGB', (len(ims) * (tw + 20) + 20, th + 40), (245, 242, 236))
    for i, im in enumerate(ims): sheet.paste(im.resize((tw, th), Image.LANCZOS), (20 + i * (tw + 20), 20))
    sheet.save(out)


def compare(ref, mine, out, cfg):
    a, b = Image.open(ref).convert('RGB'), Image.open(mine).convert('RGB'); h = 900
    a = a.resize((int(a.width * h / a.height), h), Image.LANCZOS); b = b.resize((int(b.width * h / b.height), h), Image.LANCZOS)
    sheet = Image.new('RGB', (a.width + b.width + 60, h + 110), (245, 242, 236)); sheet.paste(a, (20, 90)); sheet.paste(b, (a.width + 40, 90))
    d = ImageDraw.Draw(sheet); f = C.font(cfg, 'body', 40)
    d.text((20 + a.width / 2, 45), '参考图', font=f, fill=(90, 90, 90), anchor='mm'); d.text((a.width + 40 + b.width / 2, 45), '成品', font=f, fill=(90, 90, 90), anchor='mm')
    sheet.save(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--config', default='config/brand.yaml'); ap.add_argument('--layout', default='config/layout.yaml')
    ap.add_argument('--draft', required=True, help='稿件目录，里面要有 pages.yaml'); ap.add_argument('--variant')
    ap.add_argument('--only', choices=['cover', 'inner']); ap.add_argument('--seed', type=int, default=7)
    ap.add_argument('--refs', help='参考图目录，默认 <data>/refs/<稿件ID>/（<data> = 稿件目录的上两级）')
    ap.add_argument('--no-reference-confirmed', action='store_true', help='用户看过警告并二次确认：没有参考图也出图（极度不推荐，会记进评审回流库）')
    a = ap.parse_args()
    cfg = C.load_yaml(a.config); lay = C.load_yaml(a.layout); pages = C.load_yaml(os.path.join(a.draft, 'pages.yaml'))
    draft_dir = os.path.abspath(a.draft); did = os.path.basename(draft_dir.rstrip('/')); root = os.path.dirname(os.path.dirname(draft_dir))
    probs = reference_problems(lay, a.refs or os.path.join(root, 'refs', did))
    if probs and not a.no_reference_confirmed:
        sys.exit('✗ 还没登记参考图，不出图。\n  ' + '\n  '.join(probs) +
                 '\n请让用户二选一：\n  1.【推荐·默认】给参考图，做针对性修改：把参考图放进 data/refs/' + did +
                 '/，按 templates/参考图拆解清单.md 把拆解写进 layout.yaml 的 reference\n  2. 没有参考图（极度不推荐）：没有参考图做出来的图片审美会非常差。'
                 '用户二次确认后加 --no-reference-confirmed')
    if probs:
        print('⚠ 没有参考图出图（用户已二次确认）：审美会明显变差，评审时请再要一次参考图。', file=sys.stderr); log_no_reference(root, did)
    if a.variant:
        v = (lay.get('variants') or {}).get(a.variant)
        if v is None and not (pages.get('variants') or {}).get(a.variant): sys.exit(f'layout 和 pages.yaml 里都没有 variants.{a.variant}')
        lay = deep_merge(lay, v or {}); lay['_variant_spec'] = v or {}
    lay = apply_page_overrides(lay, pages, a.variant)
    clamp_price(lay, root)
    r = R(cfg, lay, a.draft); out = os.path.join(a.draft, 'out' + (f'_{a.variant}' if a.variant else '')); os.makedirs(out, exist_ok=True)
    files = []
    if a.only != 'inner':
        p = os.path.join(out, 'P01.png'); r.cover(pages.get('cover', {}), a.seed).convert('RGB').save(p); files.append(p); print('出图', p)
    if a.only != 'cover':
        for i, pg in enumerate(pages.get('inner', []) or [], start=2):
            p = os.path.join(out, f'P{i:02d}.png'); r.inner(pg, a.seed, i).convert('RGB').save(p); files.append(p); print('出图', p)
    if len(files) > 1: preview(files, os.path.join(out, 'preview.png')); print('预览', os.path.join(out, 'preview.png'))
    rdir = a.refs or os.path.join(root, 'refs', did)
    if not probs and a.only != 'inner' and not a.variant:   # 「参考图 | 成品」对比图：第 5 步给用户看，问哪里还要改
        refs = sorted(f for f in os.listdir(rdir) if f.lower().endswith(IMG_EXT))
        compare(os.path.join(rdir, refs[0]), os.path.join(out, 'P01.png'), os.path.join(out, '参考对比.png'), cfg); print('对比', os.path.join(out, '参考对比.png'))
    if MISSING:
        print(f'⚠ 有 {len(set(MISSING))} 项没确认、图上显示为{C.UNKNOWN}：{", ".join(sorted(set(MISSING)))}——确认前不能发布', file=sys.stderr)
    face = C.get(cfg, 'face_policy.mode', '')
    if face in ('ai_swap',):
        print('提醒：本品牌人脸规则是 AI 换脸，用了换脸照片的图发布时必须勾选「含AI生成内容」。', file=sys.stderr)


if __name__ == '__main__':
    main()
