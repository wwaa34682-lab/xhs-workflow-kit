#!/usr/bin/env python3
"""第 8 步 数据回收：聚光（小红书广告后台）导出 CSV → 投放效果库 + 帖子成绩单 + 基线/目标线 + 总结图。可反复运行。

用法
  # 导入一份新的聚光导出（计划列表必填，创意数据可选），然后重算
  python scripts/recover_juguang.py --config config/brand.yaml --data data \
      --plan ~/Downloads/计划-列表数据.csv [--creative ~/Downloads/创意-数据.csv] --range "2026-01-01 ~ 2026-03-31"
  # 用已登记的导出重算（改了 投放映射.csv 之后）
  python scripts/recover_juguang.py --config config/brand.yaml --data data
  # 可选：自然流量（创作者中心导出的笔记数据）
  python scripts/recover_juguang.py ... --organic ~/Downloads/笔记数据.csv
  # 模拟模式：没有新帖的真实投流数据时，用历史计划“扮演”新帖的几个版本，把复盘流程跑通（只写 data/sim/，不碰正式表）
  python scripts/recover_juguang.py --config config/brand.yaml --data data --sim \
      --proxy "A=历史计划名1" --proxy "B=历史计划名2|历史计划名3" --draft D001

规则（不编造）
  - 计划→笔记只认三种依据：① 投放映射.csv 里人工填的笔记ID；② 计划名≈自有帖/稿件标题；③ 创意名≈标题。②③置信度=中，需在聚光后台核对笔记ID。
  - 计划名和创意名指向不同帖子 → 「冲突·待核」，不计入任何帖子；对不上 → 「待补」，不猜。
  - 投放映射.csv 里 匹配方式=排除 的计划（以及绑定到被排除笔记ID 的计划）不进入任何统计。
  - 创意→计划：两份导出里 消费/展现/点击 三项完全相同即视为同一投放单元。
"""
import argparse, os, re, sys, shutil, statistics, datetime, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C
import organic as O

EMO = re.compile('[\u2600-\u27BF\U0001F000-\U0001FAFF\u200b\ufe0f]')
COL = dict(plan=['计划名称', '计划名'], creative=['创意名称', '创意名'], spend=['消费', '花费', '消耗'],
           imp=['展现量', '展现数', '曝光量'], click=['点击量', '点击数'], inter=['互动量', '互动数'],
           dm_in=['私信进线数'], dm_open=['私信开口数'],
           lead=['私信留资数', '留资数', '表单提交数', '线索数', '表单留资数', '表单预约数', '预约数', '到店数', '到院数'])
MAP_COLS = C.schema('投放映射')
EXCL = '排除'


def norm(s):
    s = EMO.sub('', str(s or '')).strip()
    s = re.sub(r'(\(\d+\)|\d)$', '', s).strip()
    return re.sub(r'[\s，,！!？?｜|“”"：:。.\-—_【】\[\]（）()]', '', s)


def ctr(c, i): return c / i if i else 0.0
def cpl(s, l): return s / l if l else None


class Ctx:
    def __init__(self, cfg, paths, sim=False):
        self.cfg, self.paths, self.sim = cfg, paths, sim
        base = paths['sim'] if sim else paths['root']
        self.exports = os.path.join(base, 'exports')
        self.cur_file = os.path.join(self.exports, '当前导出.json')
        self.map_file = os.path.join(paths['sim'], '投放映射.csv') if sim else C.table_path(paths, '投放映射')
        self.out = os.path.join(paths['sim'], 'out') if sim else paths['out']
        jg = cfg.get('juguang', {}) or {}
        self.min_spend = float(jg.get('min_spend_for_rank', 100))
        self.min_imp = int(jg.get('min_impressions_for_ctr', 1000))
        lf = jg.get('lead_field')
        self.lead_cols = [lf] + COL['lead'] if lf and lf != 'auto' and not C.is_unknown(lf) else COL['lead']

    def current(self):
        if os.path.exists(self.cur_file):
            return json.load(open(self.cur_file, encoding='utf-8'))
        return {}

    def register(self, plan, creative=None, rng=None, account=None):
        os.makedirs(self.exports, exist_ok=True); cur = self.current()
        for key, src in (('plan', plan), ('creative', creative)):
            if not src: cur[key] = '' if key == 'creative' else cur.get(key, ''); continue
            src = os.path.expanduser(src); dst = os.path.basename(src)
            if rng:
                tag = re.sub(r'[\s/:]', '', rng).replace('~', '-')
                base = re.sub(r'(\s*\(\d+\))?\.csv$', '', dst)
                dst = (base if tag in base else f'{base}_{tag}') + '.csv'
            if os.path.abspath(src) != os.path.abspath(os.path.join(self.exports, dst)):
                shutil.copy2(src, os.path.join(self.exports, dst))
            cur[key] = dst
        if rng: cur['range'] = rng
        cur['account'] = account or cur.get('account') or C.get(self.cfg, 'juguang.account_name', '') or ''
        C.dump_json(cur, self.cur_file); return cur

    # ------------------------------------------------------------ load
    def load(self):
        cur = self.current()
        if not cur.get('plan'):
            sys.exit('还没有登记聚光导出：请加 --plan <计划列表导出.csv>')
        plans = []
        rows_ = C.read_csv(os.path.join(self.exports, cur['plan']))
        hdr = list(rows_[0].keys()) if rows_ else []
        lf = C.get(self.cfg, 'juguang.lead_field')
        if hdr and not any(c in hdr for c in self.lead_cols):
            print(f'⚠ 导出里找不到任何留资列（{"、".join(self.lead_cols[:5])}…），留资会全部算成 0：先和用户核对 juguang.lead_field，不要据此下结论', file=sys.stderr)
        elif hdr and lf and lf != 'auto' and not C.is_unknown(lf) and lf not in hdr:
            print(f'⚠ 你确认的留资列「{lf}」不在导出里，暂用「{next(c for c in self.lead_cols if c in hdr)}」：请让用户确认', file=sys.stderr)
        elif hdr and (not lf or lf == 'auto'):
            print(f'留资列自动识别为「{next(c for c in self.lead_cols if c in hdr)}」：请让用户确认一次，写进 juguang.lead_field', file=sys.stderr)
        for r in rows_:
            name = str(C.pick(r, COL['plan'])).strip()
            if not name or name.startswith('合计') or name.startswith('总计'): continue
            plans.append(dict(计划名称=name, 消费=C.num(C.pick(r, COL['spend'])), 展现量=int(C.num(C.pick(r, COL['imp']))),
                              点击量=int(C.num(C.pick(r, COL['click']))), 互动量=int(C.num(C.pick(r, COL['inter']))),
                              私信进线数=int(C.num(C.pick(r, COL['dm_in']))), 私信开口数=int(C.num(C.pick(r, COL['dm_open']))),
                              留资数=int(C.num(C.pick(r, self.lead_cols))), 创意名称=str(C.pick(r, COL['creative'])).strip()))
        cp = os.path.join(self.exports, cur.get('creative') or '')
        if cur.get('creative') and os.path.exists(cp):
            used = set()
            for c in C.read_csv(cp):
                cname = str(C.pick(c, COL['creative'])).strip()
                if not cname or cname.startswith('合计'): continue
                key = (round(C.num(C.pick(c, COL['spend'])), 2), int(C.num(C.pick(c, COL['imp']))), int(C.num(C.pick(c, COL['click']))))
                for i, p in enumerate(plans):
                    if i not in used and not p['创意名称'] and (round(p['消费'], 2), p['展现量'], p['点击量']) == key:
                        p['创意名称'] = cname; used.add(i); break
        return plans, cur

    # ------------------------------------------------------------ mapping
    def titles(self):
        t = {}
        for r in C.load_table(self.paths, '爆款样本库_样本帖子'):
            if r.get('来源类型', '').startswith('自有') and r.get('标题'):
                t[r['样本ID']] = (norm(r['标题']), r.get('笔记ID', ''), r['标题'])
        for r in C.load_table(self.paths, '发布队列'):
            if r.get('稿件ID') and r.get('标题'):
                t.setdefault(r['稿件ID'], (norm(r['标题']), r.get('笔记ID', ''), r['标题']))
        return t

    def load_map(self):
        return {r['计划名称']: r for r in C.read_csv(self.map_file)}

    def seed_map(self, plans):
        m = self.load_map(); T = self.titles(); by_note = {v[1]: k for k, v in T.items() if v[1]}
        drafts = {r.get('稿件ID') for r in C.load_table(self.paths, '发布队列') if r.get('稿件ID')}

        def hit(name):
            n = norm(name)
            if len(n) < 4: return ''
            for sid, (t, _, _) in T.items():
                if t and (n == t or t.startswith(n) or n.startswith(t)): return sid
            return ''
        for p in plans:
            k = p['计划名称']
            if k in m:
                r = m[k]
                if r.get('笔记ID') and not r.get('关联样本ID') and by_note.get(r['笔记ID']):
                    r.update(关联样本ID=by_note[r['笔记ID']], 匹配方式=r.get('匹配方式') or '笔记ID', 置信度=r.get('置信度') or '高')
                continue
            a, b = hit(k), hit(p['创意名称'])
            row = dict(计划名称=k, 笔记ID='', 关联样本ID='', 匹配方式='', 置信度='', 依据='', 备注='')
            nm = re.match(r'^(?:【模拟】)?([A-Za-z]+\d+)-([A-Za-z0-9]+)(?=$|[\s_｜|])', k)
            if nm and nm.group(1) in drafts:
                row.update(关联样本ID=f'{nm.group(1)}-{nm.group(2)}', 匹配方式='计划命名', 置信度='高',
                           依据=f'计划名按 A/B 方案命名：稿件 {nm.group(1)} 版本 {nm.group(2)}')
            elif a and b and a != b:
                row.update(匹配方式='冲突', 置信度='待核', 依据=f'计划名≈{a}，创意名≈{b}', 备注='在聚光后台核对该计划绑定的笔记ID')
            elif a or b:
                row.update(关联样本ID=a or b, 笔记ID=T[a or b][1], 匹配方式='计划名≈标题' if a else '创意名≈标题', 置信度='中',
                           依据='名称与自有帖/稿件标题一致（去emoji/标点/末尾序号）', 备注='待在聚光后台核对笔记ID')
            else:
                row.update(匹配方式='未匹配', 置信度='待补', 依据='计划名/创意名与自有帖、稿件标题都对不上，且无笔记ID',
                           备注='待补：在聚光后台查该计划绑定的笔记ID，填进投放映射.csv')
            m[k] = row
        C.write_csv(self.map_file, list(m.values()), MAP_COLS)
        return m

    @staticmethod
    def excluded(p, m):
        ex_notes = {r['笔记ID'] for r in m.values() if r.get('匹配方式') == EXCL and r.get('笔记ID')}
        r = m.get(p['计划名称'], {})
        return r.get('匹配方式') == EXCL or bool(r.get('笔记ID') and r['笔记ID'] in ex_notes)

    # ------------------------------------------------------------ metrics
    def baselines(self, plans):
        S = sum(p['消费'] for p in plans); I = sum(p['展现量'] for p in plans)
        Cc = sum(p['点击量'] for p in plans); L = sum(p['留资数'] for p in plans)
        big = [p for p in plans if p['消费'] >= self.min_spend]
        bc = sorted(ctr(p['点击量'], p['展现量']) for p in big if p['展现量'])
        lc = sorted(cpl(p['消费'], p['留资数']) for p in big if p['留资数'])
        q = lambda xs, i: statistics.quantiles(xs, n=4)[i] if len(xs) >= 4 else None
        zero = [p for p in plans if not p['留资数']]
        return dict(计划数=len(plans), 消费=round(S, 2), 展现=I, 点击=Cc, 留资=L, CTR=ctr(Cc, I), CPC=S / Cc if Cc else None,
                    CPL=cpl(S, L), 点击留资率=L / Cc if Cc else None, n_消费达标=len(big), n_有留资且消费达标=len(lc),
                    CTR中位=statistics.median(bc) if bc else None, CTR_P75=q(bc, 2),
                    CPL中位=statistics.median(lc) if lc else None, CPL_P25=q(lc, 0),
                    零留资计划数=len(zero), 零留资消费=round(sum(p['消费'] for p in zero), 2))

    def targets(self, b):
        c = b['CPL']
        return dict(CTR及格=b['CTR'] if b['展现'] else None, CTR优秀=b['CTR_P75'], CPL及格=c, CPL优秀=b['CPL_P25'],
                    CTR门槛_展现=self.min_imp, CPL门槛_消费=round(2 * c, 2) if c else None, CPL门槛_留资=3,
                    止损_消费=round(c, 2) if c else None,
                    说明=(f'CTR 需展现≥{self.min_imp} 才判；CPL 需消费≥{2*c:.0f} 元（2×账户CPL）或留资≥3 才判；消费≥{c:.0f} 元仍 0 留资→换创意/停投'
                        if c else f'CTR 需展现≥{self.min_imp} 才判；本区间无留资，CPL 目标线待补') +
                       ('' if b['CTR_P75'] is not None else '；有效计划不足 4 个，优秀线（P75/P25）待补'))

    def scorecard(self, plans, m):
        groups = {}
        for p in plans:
            r = m.get(p['计划名称'], {})
            sid = r.get('关联样本ID', '')
            if not sid or r.get('置信度') in ('待补', '待核'): continue
            groups.setdefault(sid, []).append((p, r))
        T = self.titles(); out = []
        for sid, rows in groups.items():
            S = sum(p['消费'] for p, _ in rows); I = sum(p['展现量'] for p, _ in rows)
            Cc = sum(p['点击量'] for p, _ in rows); L = sum(p['留资数'] for p, _ in rows)
            out.append(dict(帖子=sid, 标题=T.get(sid, ('', '', '待补'))[2], 关联计划=' / '.join(p['计划名称'] for p, _ in rows),
                            计划数=len(rows), 消费=round(S, 2), 展现=I, 点击=Cc, CTR=C.pct(ctr(Cc, I)) if I else '—', 留资=L,
                            CPL=C.money(cpl(S, L)), 关联置信度='、'.join(sorted({r.get('置信度', '') for _, r in rows}))))
        return sorted(out, key=lambda r: (cpl(r['消费'], r['留资']) is None, cpl(r['消费'], r['留资']) or 0, -r['消费']))

    def ads_rows(self, plans, m, cur):
        rows = []
        for p in plans:
            r = m.get(p['计划名称'], {})
            note = [r.get('备注', '')] if r.get('备注') else []
            if self.excluded(p, m): note.append('已排除，不计入分析')
            rows.append(dict(计划名称=p['计划名称'], 创意名称=p['创意名称'], 笔记ID=r.get('笔记ID', ''), 消费=f"{p['消费']:.2f}",
                             展现量=p['展现量'], 点击量=p['点击量'], 点击率=C.pct(ctr(p['点击量'], p['展现量'])),
                             平均点击成本=f"{p['消费']/p['点击量']:.2f}" if p['点击量'] else '', 互动量=p['互动量'],
                             私信进线数=p['私信进线数'], 私信开口数=p['私信开口数'], 留资数=p['留资数'],
                             留资成本=C.money(cpl(p['消费'], p['留资数'])) if p['留资数'] else '',
                             关联样本ID=r.get('关联样本ID', ''), 匹配方式=r.get('匹配方式', ''), 置信度=r.get('置信度', ''),
                             匹配依据=r.get('依据', ''), 数据区间=cur.get('range', ''),
                             数据来源=('模拟·' if self.sim else '') + f"聚光导出 {cur.get('plan','')}" + (f"（{cur['account']}）" if cur.get('account') else ''),
                             备注='；'.join(x for x in note if x)))
        return rows

    def run(self, render=True, targets_override=None):
        allp, cur = self.load(); m = self.seed_map(allp)
        plans = [p for p in allp if not self.excluded(p, m)]
        ex = [p for p in allp if self.excluded(p, m)]
        bx = getattr(self, 'baseline_exclude', None)
        bplans = [q for q in plans if not (bx and m.get(q['计划名称'], {}).get('关联样本ID', '').startswith(bx))] if bx else plans
        b = self.baselines(bplans); tg = targets_override or self.targets(b); card = self.scorecard(plans, m)
        if bx: b['说明'] = f'基线已排除稿件 {bx} 的计划（{len(plans) - len(bplans)} 个）'
        os.makedirs(self.out, exist_ok=True)
        ads = self.ads_rows(allp, m, cur)
        if self.sim:
            C.write_csv(os.path.join(self.out, '投放效果库_模拟.csv'), ads, C.schema('投放效果库'))
        else:
            C.save_table(self.paths, '投放效果库', ads)
        if card:
            C.write_csv(os.path.join(self.out, '数据回收_帖子成绩单.csv'), card, list(card[0].keys()))
        unmatched = [p for p in plans if m.get(p['计划名称'], {}).get('置信度') in ('待补', '待核')]
        res = dict(标注=C.SIM_LABEL if self.sim else '真实数据', 数据区间=cur.get('range', ''), 账户=cur.get('account', ''),
                   导出=cur.get('plan'), 生成时间=f'{datetime.datetime.now():%Y-%m-%d %H:%M}',
                   排除计划=[dict(计划名称=p['计划名称'], 消费=p['消费'], 留资=p['留资数']) for p in ex],
                   基线=b, 目标线=tg, 成绩单=card,
                   未关联=dict(计划数=len(unmatched), 消费=round(sum(p['消费'] for p in unmatched), 2),
                            留资=sum(p['留资数'] for p in unmatched)))
        C.dump_json(res, os.path.join(self.out, '数据回收_基线.json'))
        self.write_md(res)
        if render: self.render(res)
        if not self.sim:
            hist = os.path.join(self.out, '数据回收_导入历史.csv')
            rows = C.read_csv(hist)
            rows.append(dict(导入时间=res['生成时间'], 数据区间=res['数据区间'], 计划导出=res['导出'], 分析计划数=b['计划数'],
                             消费=f"{b['消费']:.2f}", 展现=b['展现'], 点击=b['点击'], CTR=C.pct(b['CTR']), 留资=b['留资'],
                             CPL=C.money(b['CPL']), 排除计划数=len(ex)))
            C.write_csv(hist, rows, list(rows[-1].keys()))
        return res

    def write_md(self, r):
        b, tg = r['基线'], r['目标线']
        L = [f"# 数据回收（第 8 步）{'——' + C.SIM_LABEL if self.sim else ''}", '',
             f"- 数据区间：{r['数据区间'] or '待补'}；导出：{r['导出']}；账户：{r['账户'] or '—'}",
             f"- 分析口径：{b['计划数']} 个计划" + (f"（已排除 {len(r['排除计划'])} 个：{'、'.join(p['计划名称'] for p in r['排除计划'])}）" if r['排除计划'] else ''),
             f"- 合计：消费 {b['消费']:,.2f} 元，展现 {b['展现']:,}，点击 {b['点击']:,}，CTR {C.pct(b['CTR'])}，留资 {b['留资']}，CPL {C.money(b['CPL'])} 元",
             f"- 0 留资计划 {b['零留资计划数']} 个，共消费 {b['零留资消费']:,.2f} 元",
             *([f"- {b['说明']}"] if b.get('说明') else []),
             f"- 还有 {r['未关联']['计划数']} 个计划没关联到帖子（消费 {r['未关联']['消费']:,.2f} 元，留资 {r['未关联']['留资']}）→ 在 投放映射.csv 补笔记ID", '',
             '## 下一篇要打败的目标线', '', '| 指标 | 及格（账户均值） | 优秀 |', '|---|---|---|',
             f"| CTR | ≥ {C.pct(tg['CTR及格'])} | ≥ {C.pct(tg['CTR优秀'])}（P75，消费≥{self.min_spend:.0f} 元的计划） |",
             f"| CPL（元/留资） | ≤ {C.money(tg['CPL及格'])} | ≤ {C.money(tg['CPL优秀'])}（P25，有留资的计划） |", '',
             f"判定门槛：{tg['说明']}", '', '## 帖子成绩单（按 CPL 从低到高）', '']
        if r['成绩单']:
            L += ['| 帖子 | 标题 | 计划数 | 消费 | CTR | 留资 | CPL | 置信度 |', '|---|---|---|---|---|---|---|---|']
            L += [f"| {c['帖子']} | {c['标题']} | {c['计划数']} | {c['消费']:,.2f} | {c['CTR']} | {c['留资']} | {c['CPL']} | {c['关联置信度']} |" for c in r['成绩单']]
        else:
            L.append('（还没有能关联到帖子的计划）')
        L += ['', '> 样本量小时所有规律都只是方向。把想写进风格锁的规律先写成「提议·待专家确认」，专家确认后再生效（见 steps/10）。']
        open(os.path.join(self.out, '数据回收_结论.md'), 'w', encoding='utf-8').write('\n'.join(L) + '\n')

    def render(self, r):
        from PIL import Image, ImageDraw
        b, tg = r['基线'], r['目标线']; W, pad = 1600, 48
        dark = C.hex2rgb(C.get(self.cfg, 'brand.colors.dark'), (40, 40, 40))
        acc = C.hex2rgb(C.get(self.cfg, 'brand.colors.accent'), (230, 120, 30))
        img = Image.new('RGB', (W, 2400), (250, 248, 243)); d = ImageDraw.Draw(img)
        F = lambda s: C.font(self.cfg, 'body', s)
        y = pad
        if self.sim:
            d.rectangle([0, 0, W, 70], fill=(200, 40, 40)); d.text((W / 2, 35), C.SIM_LABEL, font=F(36), fill='white', anchor='mm'); y = 100
        d.text((pad, y), f"数据回收总结 · {r['数据区间'] or ''}", font=F(48), fill=dark); y += 80
        kpi = [('计划数', b['计划数']), ('消费(元)', f"{b['消费']:,.0f}"), ('展现', f"{b['展现']:,}"), ('点击', f"{b['点击']:,}"),
               ('CTR', C.pct(b['CTR'])), ('留资', b['留资']), ('CPL', C.money(b['CPL']))]
        bw = (W - 2 * pad) / len(kpi)
        for i, (k, v) in enumerate(kpi):
            x = pad + i * bw
            d.rounded_rectangle([x + 4, y, x + bw - 4, y + 110], 14, fill='white', outline=(220, 215, 205), width=2)
            d.text((x + 18, y + 12), k, font=F(22), fill=(120, 120, 120)); d.text((x + 18, y + 48), str(v), font=F(36), fill=dark)
        y += 140
        d.text((pad, y), '目标线', font=F(34), fill=acc); y += 52
        for t in [f"CTR 及格 ≥ {C.pct(tg['CTR及格'])}，优秀 ≥ {C.pct(tg['CTR优秀'])}",
                  f"CPL 及格 ≤ {C.money(tg['CPL及格'])}，优秀 ≤ {C.money(tg['CPL优秀'])}"] + C.wrap_text(d, tg['说明'], F(24), W - 2 * pad):
            d.text((pad + 10, y), t, font=F(26), fill=dark); y += 40
        y += 20; d.text((pad, y), '帖子成绩单（按 CPL）', font=F(34), fill=acc); y += 56
        cols = ['帖子', '标题', '消费', 'CTR', '留资', 'CPL']; wd = [180, 700, 160, 140, 100, 160]
        x = pad
        for c, w_ in zip(cols, wd): d.text((x, y), c, font=F(24), fill=(120, 120, 120)); x += w_
        y += 40
        for c in r['成绩单'][:15]:
            x = pad
            for v, w_ in zip([c['帖子'], c['标题'], f"{c['消费']:,.0f}", c['CTR'], c['留资'], c['CPL']], wd):
                s = str(v)
                while d.textlength(s, font=F(24)) > w_ - 16 and len(s) > 2: s = s[:-2] + '…'
                d.text((x, y), s, font=F(24), fill=dark); x += w_
            y += 38
        if not r['成绩单']: d.text((pad, y), '（还没有能关联到帖子的计划）', font=F(24), fill=dark); y += 40
        img.crop((0, 0, W, y + pad)).save(os.path.join(self.out, '数据回收_总结.png'))


# ---------------------------------------------------------------- organic (optional)
ORG = dict(title=['笔记标题', '标题', '笔记名称'], note=['笔记ID', '笔记id'], date=['发布时间', '发布日期'],
           imp=['曝光', '曝光量', '曝光数'], view=['观看', '观看量', '阅读量', '浏览量'], like=['点赞', '点赞数'],
           fav=['收藏', '收藏数'], cmt=['评论', '评论数'], share=['分享', '分享数'], fans=['涨粉', '涨粉数', '新增关注'],
           ask=['咨询数', '私信咨询', '到店咨询', '咨询'])


def organic(ctx, path, rng):
    rows = []
    T = ctx.titles()
    # 自然流量 A/B：发布队列里登记了 版本 + 笔记ID 的帖子，按笔记ID 关联到 <稿件ID>-<版本>
    by_note = {q['笔记ID']: f"{q['稿件ID']}-{q['版本或套系'].split()[0]}" for q in C.load_table(ctx.paths, '发布队列')
               if q.get('笔记ID') and q.get('版本或套系') and q.get('稿件ID') and '/' not in q['版本或套系']}
    for r in C.read_csv(os.path.expanduser(path)):
        t = str(C.pick(r, ORG['title'])).strip()
        if not t: continue
        sid = by_note.get(str(C.pick(r, ORG['note'])).strip(), '') or \
            next((k for k, v in T.items() if v[0] and (v[0] == norm(t) or v[0].startswith(norm(t)))), '')
        rows.append(dict(笔记ID=C.pick(r, ORG['note']), 标题=t, 关联样本ID=sid, 发布日期=C.pick(r, ORG['date']),
                         **{k: int(C.num(C.pick(r, ORG[e]))) for k, e in [('曝光', 'imp'), ('观看', 'view'), ('点赞', 'like'),
                                                                          ('收藏', 'fav'), ('评论', 'cmt'), ('分享', 'share'), ('涨粉', 'fans')]},
                         咨询数=(int(C.num(C.pick(r, ORG['ask']))) if C.pick(r, ORG['ask']) != '' else ''),
                         数据区间=rng or '', 数据来源=f'创作者中心导出 {os.path.basename(path)}'))
    C.save_table(ctx.paths, '自然流量库', rows)
    v = [r['观看'] for r in rows]
    print(f"自然流量：{len(rows)} 篇，观看中位 {statistics.median(v) if v else 0}；写入 tables/自然流量库.csv")


# ---------------------------------------------------------------- simulation
SUMC = ['消费', '展现量', '点击量', '互动量', '私信进线数', '私信开口数'] + COL['lead']   # 留资的所有别名都要累加（含用户确认的 lead_field）


def simulate(cfg, paths, proxies, draft, rng):
    """用历史计划的真实数字扮演新稿件的几个版本 → data/sim/。目标线仍取正式（真实）口径。"""
    real = Ctx(cfg, paths); allp, cur = real.load()
    src = C.read_csv(os.path.join(real.exports, cur['plan'])); cols = list(src[0].keys())
    out, mp = [], []
    for spec in proxies:
        var, names = spec.split('=', 1); names = [n.strip() for n in names.split('|') if n.strip()]
        hit = [r for r in src if str(C.pick(r, COL['plan'])).strip() in names]
        if len(hit) != len(names):
            sys.exit(f'替身计划没找到：{set(names) - {str(C.pick(r, COL["plan"])).strip() for r in hit}}')
        o = {c: '-' for c in cols}; pc = next(c for c in COL['plan'] if c in cols); o[pc] = f'【模拟】{draft}-{var}'
        for c in cols:
            if c in SUMC or c in real.lead_cols: o[c] = round(sum(C.num(r[c]) for r in hit), 2)
        out.append(o)
        mp.append(dict(计划名称=o[pc], 关联样本ID=f'{draft}-{var}', 匹配方式='模拟替身', 置信度='模拟',
                       依据=f"{C.SIM_LABEL} 数值取自历史计划：{' + '.join(names)}"))
    sim = Ctx(cfg, paths, sim=True); os.makedirs(sim.exports, exist_ok=True)
    p = os.path.join(sim.exports, f'计划-列表数据_SIM_{draft}.csv'); C.write_csv(p, out, cols)
    C.write_csv(sim.map_file, mp, MAP_COLS)
    sim.register(p, None, rng or '模拟区间', C.SIM_LABEL)
    bj = os.path.join(real.out, '数据回收_基线.json')
    if os.path.exists(bj):
        tg = json.load(open(bj, encoding='utf-8'))['目标线']
    else:  # 只在内存里算真实口径，不写正式表
        m = real.load_map(); tg = real.targets(real.baselines([q for q in allp if not real.excluded(q, m)]))
    res = sim.run(targets_override=tg)
    res['目标线来源'] = '正式（真实）数据回收口径'
    C.dump_json(res, os.path.join(sim.out, '数据回收_基线.json'))
    print(f'模拟导出：{p}\n模拟输出：{sim.out}（正式表未改动）')
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--config', default='config/brand.yaml'); ap.add_argument('--data', default='data')
    ap.add_argument('--plan'); ap.add_argument('--creative'); ap.add_argument('--range'); ap.add_argument('--account')
    ap.add_argument('--organic', help='可选：创作者中心导出的笔记数据 CSV')
    ap.add_argument('--sim', action='store_true', help='模拟模式（只写 data/sim/）')
    ap.add_argument('--proxy', action='append', default=[], help='模拟替身：版本=历史计划名1|历史计划名2')
    ap.add_argument('--draft', default='D001', help='模拟时的稿件ID')
    ap.add_argument('--organic-proxy', action='append', default=[], help='没有聚光时的模拟替身：版本=历史帖子标题1|标题2（取自自然流量库）')
    ap.add_argument('--exclude', action='append', default=[], help='把这个计划排除出统计（未关联、和本品牌无关的计划），可多次')
    ap.add_argument('--why', default='', help='排除原因，照抄用户原话')
    ap.add_argument('--baseline-exclude', help='算基线时排除这篇稿件的计划（如 D001），避免“和含有自己的平均数比”')
    a = ap.parse_args()
    cfg = C.load_yaml(a.config); paths = C.data_paths(a.data)
    if a.exclude:
        ctx0 = Ctx(cfg, paths); m = ctx0.load_map()
        for k in a.exclude:
            r = m.get(k) or dict(计划名称=k)
            r.update(匹配方式=EXCL, 置信度='人工', 依据=f'用户：{a.why}' if a.why else '用户要求排除', 备注='已排除，不计入分析'); m[k] = r
        C.write_csv(ctx0.map_file, list(m.values()), MAP_COLS); print(f'已排除 {len(a.exclude)} 个计划：' + '、'.join(a.exclude))
        if not (a.plan or ctx0.current().get('plan')): return
    if a.sim:
        if a.organic_proxy:
            O.simulate(cfg, paths, a.organic_proxy, a.draft, a.range); return
        if not a.proxy: sys.exit('模拟模式需要至少两个 --proxy（有聚光：历史计划名）或 --organic-proxy（没有聚光：历史帖子标题）')
        simulate(cfg, paths, a.proxy, a.draft, a.range); return
    ctx = Ctx(cfg, paths); ctx.baseline_exclude = a.baseline_exclude
    if a.plan: ctx.register(a.plan, a.creative, a.range, a.account)
    if a.organic: organic(ctx, a.organic, a.range)
    if not ctx.current().get('plan'):
        rows = C.load_table(paths, '自然流量库')
        if not rows:
            sys.exit('还没有数据：有聚光加 --plan <计划列表导出.csv>；没有聚光加 --organic <创作者中心笔记数据.csv>')
        r = O.run(cfg, paths, rows, paths['out'], rng=a.range or '')
        b, tg = r['基线'], r['目标线']; pc = lambda x: C.pct(x) if x is not None else '待补'
        print(f"自然流量基线：{b['帖子数']} 篇，收藏率 {pc(b['收藏率'])}，互动率 {pc(b['互动率'])}；目标线 收藏率 及格≥{pc(tg['收藏率及格'])} 优秀≥{pc(tg['收藏率优秀'])}")
        print(f"输出：{paths['out']}/数据回收_基线.json（口径 organic）、数据回收_结论.md、数据回收_总结.png、数据回收_帖子成绩单.csv")
        return
    r = ctx.run(); b, tg = r['基线'], r['目标线']
    print(f"基线：{b['计划数']} 个计划，CTR {C.pct(b['CTR'])}，CPL {C.money(b['CPL'])}，留资 {b['留资']}，消费 {b['消费']:,.2f}")
    print(f"目标线：CTR 及格≥{C.pct(tg['CTR及格'])} 优秀≥{C.pct(tg['CTR优秀'])}；CPL 及格≤{C.money(tg['CPL及格'])} 优秀≤{C.money(tg['CPL优秀'])}")
    print(f"输出：tables/投放效果库.csv、tables/投放映射.csv、{ctx.out}/数据回收_基线.json、数据回收_结论.md、数据回收_总结.png、数据回收_帖子成绩单.csv")


if __name__ == '__main__':
    main()
