"""没有聚光时的数据口径（自然流量）：基线、目标线、帖子成绩单、A/B 判定、模拟演练。recover_juguang.py 和 ab_test.py 共用。

指标（白话）：
  观看   = 有多少人点开看了（没有观看列时用曝光）
  收藏率 = 收藏 ÷ 观看：看了的人里多少人觉得“有用、想留着”——没有投流时最能代表“想来”的信号，作为主判定
  互动率 = （点赞 + 收藏 + 评论）÷ 观看：辅助
  咨询数 = 可选手填列（私信/到店咨询），有就一并展示
门槛：一篇帖子观看 ≥ organic.min_views_for_judge（默认 300）才参与判定；不够就“样本不足，暂定”。
"""
import datetime, json, os, statistics, sys
import common as C


def cfg_min_views(cfg):
    return int(C.get(cfg, 'organic.min_views_for_judge', 300) or 300)


def row_metrics(r):
    v = int(C.num(r.get('观看'))) or int(C.num(r.get('曝光')))
    fav, like, cmt = int(C.num(r.get('收藏'))), int(C.num(r.get('点赞'))), int(C.num(r.get('评论')))
    return dict(观看=v, 收藏=fav, 点赞=like, 评论=cmt, 咨询=int(C.num(r.get('咨询数'))),
                收藏率=fav / v if v else None, 互动率=(fav + like + cmt) / v if v else None)


def baseline(rows, cfg):
    mv = cfg_min_views(cfg); ms = [row_metrics(r) for r in rows]
    V = sum(m['观看'] for m in ms); F = sum(m['收藏'] for m in ms); E = sum(m['收藏'] + m['点赞'] + m['评论'] for m in ms)
    ok = [m for m in ms if m['观看'] >= mv]
    q = lambda xs: statistics.quantiles(sorted(xs), n=4)[2] if len(xs) >= 4 else None
    b = dict(口径='organic', 帖子数=len(ms), 观看=V, 收藏=F, 收藏率=F / V if V else None, 互动率=E / V if V else None,
             观看中位=statistics.median([m['观看'] for m in ms]) if ms else 0, n_观看达标=len(ok),
             咨询=sum(m['咨询'] for m in ms))
    tg = dict(口径='organic', 收藏率及格=b['收藏率'], 收藏率优秀=q([m['收藏率'] for m in ok]),
              互动率及格=b['互动率'], 互动率优秀=q([m['互动率'] for m in ok]), 观看门槛=mv,
              说明=f'没有聚光，用自然流量判：每篇观看 ≥ {mv} 才判；收藏率（收藏 ÷ 观看）定胜负，互动率为辅。'
                 + ('' if len(ok) >= 4 else '观看达标的帖子不足 4 篇，优秀线待补。'))
    return b, tg


def scorecard(rows):
    card = []
    for r in rows:
        m = row_metrics(r); key = r.get('关联样本ID') or r.get('笔记ID') or r.get('标题')
        card.append(dict(帖子=key, 标题=r.get('标题', ''), 笔记ID=r.get('笔记ID', ''), **m))
    return sorted(card, key=lambda c: -(c['收藏率'] or 0))


def run(cfg, paths, rows, out_dir, label='真实数据', rng='', targets_override=None, render=True):
    b, tg = baseline(rows, cfg)
    if targets_override: tg = targets_override
    card = scorecard(rows)
    res = dict(标注=label, 口径='organic', 数据区间=rng, 生成时间=f'{datetime.datetime.now():%Y-%m-%d %H:%M}', 基线=b, 目标线=tg, 成绩单=card)
    os.makedirs(out_dir, exist_ok=True)
    C.dump_json(res, os.path.join(out_dir, '数据回收_基线.json'))
    if card: C.write_csv(os.path.join(out_dir, '数据回收_帖子成绩单.csv'), [{k: (C.pct(v) if k.endswith('率') else v) for k, v in c.items()} for c in card], list(card[0].keys()))
    pc = lambda x: C.pct(x) if x is not None else '待补'
    L = [f"# 数据回收（第 8 步 · 自然流量口径）{'——' + label if label != '真实数据' else ''}", '',
         f"- 帖子 {b['帖子数']} 篇，总观看 {b['观看']:,}，收藏 {b['收藏']:,}；观看达标（≥{tg['观看门槛']}）的 {b['n_观看达标']} 篇",
         f"- 收藏率 {pc(b['收藏率'])}（看了的人里多少人收藏），互动率 {pc(b['互动率'])}" + (f"；手填咨询 {b['咨询']} 次" if b['咨询'] else ''), '',
         '## 下一篇要打败的目标线', '', '| 指标 | 及格（账户平均） | 优秀（前 25%） |', '|---|---|---|',
         f"| 收藏率 | ≥ {pc(tg['收藏率及格'])} | ≥ {pc(tg['收藏率优秀'])} |", f"| 互动率 | ≥ {pc(tg['互动率及格'])} | ≥ {pc(tg['互动率优秀'])} |", '',
         f"判定门槛：{tg['说明']}", '', '## 帖子成绩单（按收藏率）', '', '| 帖子 | 标题 | 观看 | 收藏 | 收藏率 | 互动率 |', '|---|---|---|---|---|---|']
    L += [f"| {c['帖子']} | {c['标题']} | {c['观看']:,} | {c['收藏']} | {pc(c['收藏率'])} | {pc(c['互动率'])} |" for c in card]
    L += ['', '> 样本少时，规律都只是方向。想写进风格锁的，先写成「提议·待专家确认」。']
    open(os.path.join(out_dir, '数据回收_结论.md'), 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    if render: draw(cfg, res, os.path.join(out_dir, '数据回收_总结.png'))
    return res


def draw(cfg, r, path):
    from PIL import Image, ImageDraw
    b, tg = r['基线'], r['目标线']; W, pad = 1600, 48; F = lambda s: C.font(cfg, 'body', s)
    dark = C.hex2rgb(C.get(cfg, 'brand.colors.dark'), (40, 40, 40)); acc = C.hex2rgb(C.get(cfg, 'brand.colors.accent'), (230, 120, 30))
    img = Image.new('RGB', (W, 2000), (250, 248, 243)); d = ImageDraw.Draw(img); y = pad
    if r['标注'] != '真实数据':
        d.rectangle([0, 0, W, 70], fill=(200, 40, 40)); d.text((W / 2, 35), r['标注'], font=F(36), fill='white', anchor='mm'); y = 100
    d.text((pad, y), '数据回收总结 · 自然流量', font=F(48), fill=dark); y += 80
    pc = lambda x: C.pct(x) if x is not None else '待补'
    kpi = [('帖子', b['帖子数']), ('观看', f"{b['观看']:,}"), ('收藏', b['收藏']), ('收藏率', pc(b['收藏率'])), ('互动率', pc(b['互动率']))]
    bw = (W - 2 * pad) / len(kpi)
    for i, (k, v) in enumerate(kpi):
        x = pad + i * bw; d.rounded_rectangle([x + 4, y, x + bw - 4, y + 110], 14, fill='white', outline=(220, 215, 205), width=2)
        d.text((x + 18, y + 12), k, font=F(22), fill=(120, 120, 120)); d.text((x + 18, y + 48), str(v), font=F(36), fill=dark)
    y += 140; d.text((pad, y), '目标线', font=F(34), fill=acc); y += 52
    for t in [f"收藏率 及格 ≥ {pc(tg['收藏率及格'])}，优秀 ≥ {pc(tg['收藏率优秀'])}", f"互动率 及格 ≥ {pc(tg['互动率及格'])}，优秀 ≥ {pc(tg['互动率优秀'])}"] + C.wrap_text(d, tg['说明'], F(24), W - 2 * pad):
        d.text((pad + 10, y), t, font=F(26), fill=dark); y += 40
    y += 20; d.text((pad, y), '帖子成绩单（按收藏率）', font=F(34), fill=acc); y += 56
    for c in r['成绩单'][:15]:
        s = f"{c['帖子']}  {c['标题'][:22]}  观看 {c['观看']:,}  收藏率 {pc(c['收藏率'])}"
        d.text((pad, y), s, font=F(24), fill=dark); y += 38
    img.crop((0, 0, W, y + pad)).save(path)


def judge(c, tg):
    gate = c['观看'] >= (tg.get('观看门槛') or 300)

    def lv(x, good, ok):
        if x is None or ok is None: return '待补'
        if good is not None and x >= good: return '优秀'
        return '及格' if x >= ok else '不及格'
    f = lv(c['收藏率'], tg.get('收藏率优秀'), tg.get('收藏率及格')); e = lv(c['互动率'], tg.get('互动率优秀'), tg.get('互动率及格'))
    return dict(过门槛=gate, 收藏率判定=f if gate else f + '（样本不足，暂定）', 互动率判定=e if gate else e + '（样本不足，暂定）')


def simulate(cfg, paths, proxies, draft, rng):
    """没有聚光时的模拟演练：用自然流量库里的历史帖子“扮演”新稿件的几个版本 → data/sim/（正式表不改）。"""
    rows = C.load_table(paths, '自然流量库')
    if not rows: sys.exit('自然流量库是空的：先用 recover_juguang.py --organic <笔记数据.csv> 导入一次真实的创作者中心导出')
    real_b, real_tg = baseline(rows, cfg); out = []
    for spec in proxies:
        var, names = spec.split('=', 1); names = [n.strip() for n in names.split('|') if n.strip()]
        hit = [r for r in rows if r.get('标题', '').strip() in names]
        if len(hit) != len(names): sys.exit(f"替身帖子没找到：{set(names) - {r.get('标题', '').strip() for r in hit}}")
        o = {k: sum(int(C.num(r.get(k))) for r in hit) for k in ('曝光', '观看', '点赞', '收藏', '评论', '分享', '涨粉', '咨询数')}
        o.update(标题=f'【模拟】{draft}-{var}', 关联样本ID=f'{draft}-{var}', 笔记ID='', 数据来源=f"{C.SIM_LABEL} 数值取自历史帖子：{' + '.join(names)}")
        out.append(o)
    sim_out = os.path.join(paths['sim'], 'out'); os.makedirs(sim_out, exist_ok=True)
    C.write_csv(os.path.join(paths['sim'], '自然流量库_模拟.csv'), out, C.schema('自然流量库'))
    res = run(cfg, paths, out, sim_out, label=C.SIM_LABEL, rng=rng or '模拟区间', targets_override=real_tg)
    res['目标线来源'] = '正式（真实）自然流量口径'; C.dump_json(res, os.path.join(sim_out, '数据回收_基线.json'))
    print(f'模拟输出：{sim_out}（正式表未改动）'); return res
