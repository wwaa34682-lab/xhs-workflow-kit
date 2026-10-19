#!/usr/bin/env python3
"""第 9 步 投流 A/B 计划 + 第 10 步 投流复盘（打分卡 + 胜负判定 + 回写提议）。

  # 看当前基线/目标线（来自第 8 步 recover_juguang.py）
  python scripts/ab_test.py --config config/brand.yaml --data data baseline
  # 生成 A/B 测试方案（不会上线任何计划，只写方案；人在聚光里照方案建计划）
  python scripts/ab_test.py --config config/brand.yaml --data data plan --draft D001 \
      --variant "A=主版 品牌色主体" --variant "B=换背景色系（只改这一个变量）" --variant "D=真人出镜" --budget 1500
  # 复盘：先用 recover_juguang.py 回收新数据（计划名按方案命名，或在 投放映射.csv 把计划关联到 D001-A 等），再判
  python scripts/ab_test.py --config config/brand.yaml --data data verdict --draft D001 [--sim] [--write-back]

没有聚光时（第 8 步基线的口径是 organic）自动走自然流量版：plan 写“轮流发两版”的方案，verdict 按收藏率判（互动率为辅），
每版观看需 ≥ 门槛。也可以用 --metric organic / paid 强制指定。

判定规则（风格锁 SL-G13）：CPL 定胜负、CTR 为辅；CTR 需展现≥门槛；CPL 需消费≥2×账户CPL 或留资≥3，否则结论“暂定”；
消费≥1×账户CPL 仍 0 留资 → 止损。--write-back 只写“提议·待专家确认”，专家确认后才生效（ledger.py approve）。
"""
import argparse, json, os, sys, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C
import organic as O


def load_baseline(p, sim):
    f = os.path.join(p['sim'] if sim else p['root'], 'out', '数据回收_基线.json')
    if not os.path.exists(f):
        sys.exit(f'没有 {f}：先运行 recover_juguang.py' + (' --sim' if sim else ''))
    return json.load(open(f, encoding='utf-8'))


def judge(v, tg):
    ctr = v['点击'] / v['展现'] if v['展现'] else 0; cpl = v['消费'] / v['留资'] if v['留资'] else None
    ctr_gate = v['展现'] >= (tg.get('CTR门槛_展现') or 1000)
    cpl_gate = bool(tg.get('CPL门槛_消费')) and (v['消费'] >= tg['CPL门槛_消费'] or v['留资'] >= tg.get('CPL门槛_留资', 3))
    stop = bool(tg.get('止损_消费')) and v['消费'] >= tg['止损_消费'] and v['留资'] == 0

    def lv(x, good, ok, low=False):
        if x is None or ok is None: return '待补'
        if good is not None and (x <= good if low else x >= good): return '优秀'
        return '及格' if (x <= ok if low else x >= ok) else '不及格'
    ctr_lv = lv(ctr, tg.get('CTR优秀'), tg.get('CTR及格')) if ctr_gate else '样本不足'
    cpl_lv = '0留资' if cpl is None else lv(cpl, tg.get('CPL优秀'), tg.get('CPL及格'), low=True)
    if not cpl_gate: cpl_lv += '（未过门槛，暂定）'
    return dict(CTR=ctr, CPL=cpl, CTR判定=ctr_lv, CPL判定=cpl_lv, CTR过门槛=ctr_gate, CPL过门槛=cpl_gate, 止损=stop,
                距CPL门槛_消费=max(0, (tg.get('CPL门槛_消费') or 0) - v['消费']))


SIM_NO_STOP = '演练里偏弱（模拟数据不能用来停投或改预算；真实数据跑到门槛后再判）'


def sim_safe(res, organic=False):
    """模拟数据铁律：不给停投/放量/减预算这类会被照做的建议，只说“演练里的位置”。"""
    for v in res:
        d = v['决策']
        if d.startswith(('停', '降为', '收藏率较低')): v['决策'] = SIM_NO_STOP
        elif d.startswith(('放量', '主推')): v['决策'] = '演练里暂列第一（只用来走通流程，不能据此放量或改规则）'
        else: v['决策'] = '演练对照（不下结论）'


def decide(res):
    with_leads = [v for v in res if v['CPL'] is not None]
    best = min(with_leads, key=lambda v: v['CPL']) if with_leads else None
    for v in res:
        if v is best:
            v['决策'] = '放量：确认胜出' if v['CPL过门槛'] else f"放量：暂定胜出，继续跑到 CPL 门槛（还差约 {v['距CPL门槛_消费']:.0f} 元消费或 {max(0, 3 - v['留资'])} 个留资）"
        elif v['止损']: v['决策'] = '停：消费到止损线仍 0 留资'
        elif v['CTR判定'] == '不及格' and v['留资'] == 0: v['决策'] = '停：CTR 不及格且 0 留资'
        elif v['CPL过门槛'] and v['CPL判定'] == '不及格': v['决策'] = f"停：数据已够下结论（消费过了判定门槛），CPL {C.money(v['CPL'])} 不及格" + ('，CTR 也不及格' if v['CTR判定'] == '不及格' else '')
        elif v['CTR判定'] == '不及格' and v['CPL过门槛']: v['决策'] = f"降为小额对照：数据已够下结论，CPL {C.money(v['CPL'])} 及格但不是最低，CTR 不及格"
        elif v['CTR判定'] == '不及格': v['决策'] = '降为小额对照：CTR 不及格，CPL 未过门槛不下结论'
        else: v['决策'] = '保留小额对照，继续收数据'
    return best


def cmd_baseline(cfg, p, a):
    r = load_baseline(p, a.sim); b, tg = r['基线'], r['目标线']
    if r.get('口径') == 'organic':
        print(json.dumps(dict(标注=r.get('标注'), 口径='organic', 帖子数=b['帖子数'], 收藏率=C.pct(b['收藏率']), 目标线=tg), ensure_ascii=False, indent=1)); return
    print(json.dumps(dict(标注=r.get('标注'), 数据区间=r.get('数据区间'), 计划数=b['计划数'], CTR=C.pct(b['CTR']), CPL=C.money(b['CPL']),
                          目标线={k: (C.pct(v) if k.startswith('CTR') and isinstance(v, float) and v < 1 else v) for k, v in tg.items()}),
                     ensure_ascii=False, indent=1))


def metric_of(r, a):
    return a.metric or ('organic' if r.get('口径') == 'organic' else 'paid')


def save_variants(p, draft, vs):
    os.makedirs(p['out'], exist_ok=True)
    C.dump_json({k: d for k, d in vs}, os.path.join(p['out'], f'投流方案_{draft}_版本.json'))


def variant_desc(p, draft, v):
    f = os.path.join(p['out'], f'投流方案_{draft}_版本.json')
    return (json.load(open(f, encoding='utf-8')).get(v) if os.path.exists(f) else None) or ''


def plan_organic(cfg, p, a, r, vs):
    tg = r['目标线']; pc = lambda x: C.pct(x) if x is not None else '待补'
    L = [f'# 自然流量 A/B 方案 · {a.draft}（没有聚光）', '', f'> 生成于 {datetime.date.today()}。只是计划：由你亲自按顺序发布，系统不会代发。', '',
         '## 版本（一次只改一个变量）', '', '| 版本 | 说明 | 发布后登记 |', '|---|---|---|']
    L += [f'| {k} | {d} | `ledger.py queue --draft {a.draft} --variant {k} --status 已发布 --note-id <笔记ID>` |' for k, d in vs]
    L += ['', '## 怎么发', '', f'- 轮流发：{" → ".join(k for k, _ in vs)}，每版间隔 3–7 天，发在同一个星期几、同一个时段，只换要测的那一个变量。',
          '- 同一个账号发；中间不要插别的同类帖子。',
          '- ⚠ **不要把同一篇原样发两次**：图文几乎一样的笔记可能被平台判成重复内容，限流甚至影响账号。'
          '做法：两版测同一个变量（比如首图版式），但标题、正文开头和内页换成同主题下的不同角度（例如“第一次来”和“下班后来”），'
          '标签可以大部分相同。这样比的是“这个变量”的方向，不是严格对照，结论都按“暂定”看；要严格对照请用聚光（同一篇笔记挂不同创意）。', '',
          '## 怎么判（目标线来自第 8 步自然流量回收）', '',
          f"- 每版观看 ≥ {tg.get('观看门槛')} 才判；不够就继续等或换时段再发一次，结论只能“暂定”。",
          f"- 收藏率（收藏 ÷ 观看）定胜负：及格 ≥ {pc(tg.get('收藏率及格'))}，优秀 ≥ {pc(tg.get('收藏率优秀'))}；互动率为辅。",
          '- 有私信或到店咨询的，在创作者中心导出里加一列「咨询数」手填，复盘时一并看。', '',
          '## 复盘', '', '发完 7 天后导出创作者中心笔记数据 → `recover_juguang.py --organic` → `ab_test.py verdict` → 专家确认 → 写回风格锁。']
    out = os.path.join(p['out'], f'投流方案_{a.draft}.md'); open(out, 'w', encoding='utf-8').write('\n'.join(L) + '\n'); print('方案：', out)
    save_variants(p, a.draft, vs)


def cmd_plan(cfg, p, a):
    r = load_baseline(p, False); tg = r['目标线']; vs = [x.split('=', 1) for x in a.variant]
    if len(vs) < 2: sys.exit('至少两个 --variant')
    if metric_of(r, a) == 'organic': return plan_organic(cfg, p, a, r, vs)
    save_variants(p, a.draft, vs)
    gate = tg.get('CPL门槛_消费') or 0; stop = tg.get('止损_消费') or 0
    per = a.budget / len(vs) if a.budget else None
    L = [f'# 投流 A/B 测试方案 · {a.draft}', '', f'> 生成于 {datetime.date.today()}。本方案只是计划，**不会自动上线**；在聚光里由人按方案建计划、设预算。', '',
         '## 版本与计划命名（计划名必须这样写，数据回收才能自动关联）', '', '| 版本 | 说明 | 聚光计划名 | 投放映射.csv 关联样本ID |', '|---|---|---|---|']
    L += [f'| {k} | {d} | {a.draft}-{k} {d} | {a.draft}-{k} |' for k, d in vs]
    L += ['', '## 控制变量', '', '- 同一篇正文、同一定向、同一出价方式、同一时段，只换首图（或只换标题——一次只测一个变量）。',
          '- 每个版本单独一个计划（或同计划下单独创意并开“封面优选=关闭”），预算平均分。', '',
          '## 预算与门槛（目标线来自第 8 步数据回收）', '',
          f"- 及格线：CTR ≥ {C.pct(tg.get('CTR及格'))}，CPL ≤ {C.money(tg.get('CPL及格'))} 元；优秀线：CTR ≥ {C.pct(tg.get('CTR优秀'))}，CPL ≤ {C.money(tg.get('CPL优秀'))} 元",
          f"- 每个版本最少跑到：展现 ≥ {tg.get('CTR门槛_展现')}（判 CTR）；消费 ≥ {gate:,.0f} 元或留资 ≥ 3（判 CPL）",
          f"- 止损：任一版本消费 ≥ {stop:,.0f} 元仍 0 留资 → 停掉换创意",
          (f"- 总预算 {a.budget:,.0f} 元 → 每版约 {per:,.0f} 元" + ('（够到 CPL 门槛）' if gate and per >= gate else f'（不够 CPL 门槛 {gate:,.0f} 元：结论只能“暂定”，建议加预算或减少版本）'))
          if a.budget else f"- 建议总预算 ≥ {gate * len(vs):,.0f} 元（{len(vs)} 版 × CPL 门槛）", '',
          '## 阶段', '', '1. 阶段一（CTR 筛）：各版跑到展现门槛，CTR 不及格且 0 留资的先停。', '2. 阶段二（CPL 定）：剩下的跑到 CPL 门槛，CPL 最低且达标者胜出放量。',
          '3. 复盘：导出聚光 CSV → recover_juguang.py → ab_test.py verdict → 专家确认 → 写回风格锁。']
    out = os.path.join(p['out'], f'投流方案_{a.draft}.md'); os.makedirs(p['out'], exist_ok=True)
    open(out, 'w', encoding='utf-8').write('\n'.join(L) + '\n'); print('方案：', out)
    q = C.load_table(p, '发布队列'); rid = f'PQ-AB-{a.draft}'
    row = next((x for x in q if x['队列ID'] == rid), None) or {'队列ID': rid}
    if row not in q: q.append(row)
    row.update(稿件ID=a.draft, 版本或套系=' / '.join(k for k, _ in vs), 状态='投流方案·待人工建计划', 是否投流='是',
               关联投流计划=' / '.join(f'{a.draft}-{k}' for k, _ in vs), 投流目标=f"CPL ≤ {C.money(tg.get('CPL及格'))}（优秀 ≤ {C.money(tg.get('CPL优秀'))}）",
               备注=f'方案见 out/投流方案_{a.draft}.md')
    C.save_table(p, '发布队列', q); print('发布队列已登记', rid)


def verdict_organic(cfg, p, a, r):
    tg = r['目标线']; pc = lambda x: C.pct(x) if x is not None else '—'
    vs = [c for c in r['成绩单'] if str(c['帖子']).startswith(a.draft + '-')]
    if len(vs) < 2: sys.exit(f'成绩单里找不到 ≥2 个 {a.draft}-X 版本：发布时用 ledger.py queue --variant X --note-id 登记，再重新导入自然流量')
    res = []
    for c in vs:
        v = dict(版本=c['帖子'].split('-', 1)[1], 帖子=c['帖子'], 计划=c.get('标题', ''), **{k: c[k] for k in ('观看', '收藏', '点赞', '评论', '咨询', '收藏率', '互动率')})
        v.update(O.judge(v, tg)); res.append(v)
    ok = [v for v in res if v['收藏率'] is not None]
    best = max(ok, key=lambda v: (v['收藏率'], v['互动率'] or 0)) if ok else None
    for v in res:
        if v is best: v['决策'] = '主推：确认胜出' if v['过门槛'] else '主推：暂定胜出（观看没到门槛，再发一次确认）'
        elif not v['过门槛']: v['决策'] = '观看不足，暂不下结论'
        else: v['决策'] = '收藏率较低：下一篇不用这个做法' if '不及格' in v['收藏率判定'] else '保留为对照'
    if a.sim: sim_safe(res, organic=True)
    label = C.SIM_LABEL if a.sim else '真实数据'; out_dir = os.path.join(p['sim'] if a.sim else p['root'], 'out'); os.makedirs(out_dir, exist_ok=True)
    o = dict(标注=label, 口径='organic', 稿件=a.draft, 生成=f'{datetime.datetime.now():%Y-%m-%d %H:%M}', 目标线=tg, 结果=res,
             胜出=best['版本'] if best else None, 胜出已确认=bool(best and best['过门槛']))
    C.dump_json(o, os.path.join(out_dir, f'复盘_{a.draft}.json'))
    L = [f'# 自然流量复盘 · {a.draft}（{label}）', '']
    if a.sim: L += ['> 模拟演练：数字来自历史帖子“扮演”各版本，只用来走通复盘流程，**不能当作这篇的真实效果，也不能单凭它改规则**。', '']
    L += [f"目标线：收藏率 及格 ≥ {pc(tg.get('收藏率及格'))} / 优秀 ≥ {pc(tg.get('收藏率优秀'))}；每版观看 ≥ {tg.get('观看门槛')} 才判", '',
          '| 版本 | 说明 | 观看 | 收藏 | 收藏率 | 互动率 | 咨询 | 收藏率判定 | 决策 |', '|---|---|---|---|---|---|---|---|---|']
    L += [f"| {v['版本']} | {variant_desc(p, a.draft, v['版本'])} | {v['观看']:,} | {v['收藏']} | {pc(v['收藏率'])} | {pc(v['互动率'])} | {v['咨询']} | {v['收藏率判定']} | {v['决策']} |" for v in res]
    wn = (('版本 ' + best['版本'] + ('（' + variant_desc(p, a.draft, best['版本']) + '）' if variant_desc(p, a.draft, best['版本']) else '')) if best else '')
    concl = (wn + ' 在演练里暂列第一（模拟数据，不能据此改做法或改规则）' if a.sim else wn + (' 胜出' if best['过门槛'] else ' 暂定胜出（观看没到门槛）')) if best else '没有可比的数据'
    L += ['', f"**结论**：{concl}", '',
          '**下一步（人工关卡）**：专家看完决定哪条规律写进风格锁。']
    md = os.path.join(out_dir, f'复盘_{a.draft}.md'); open(md, 'w', encoding='utf-8').write('\n'.join(L) + '\n'); print('\n'.join(L[-4 - len(res):-3])); print('输出：', md)
    for v in res: v.update(消费=0, 展现=v['观看'], 点击=v['收藏'], 留资=v['咨询'], CTR=v['收藏率'], CPL=None, CTR判定=v['收藏率判定'], CPL判定=v['互动率判定'])
    render(cfg, o, os.path.join(out_dir, f'复盘_{a.draft}.png'), a.cover, organic=True)
    if a.write_back and best: write_back(p, a, best, res, organic=True)


def write_back(p, a, best, res, organic=False):
    src = '投放数据·模拟' if a.sim else ('自然流量数据' if organic else '投放数据')
    rv = C.load_table(p, '评审回流库'); n = sum(1 for x in rv if x.get('稿件ID') == a.draft) + 1
    rid = f'RV-{a.draft}-{n:02d}'; sl = C.load_table(p, '风格锁')
    sid = f"SL-{'SIM' if a.sim else ('ORG' if organic else 'AD')}-{a.draft}-{best['版本']}"
    ok = best['过门槛'] if organic else best['CPL过门槛']; desc = variant_desc(p, a.draft, best['版本']) or best.get('计划', '')
    ev = (f"收藏率 {C.pct(best['收藏率'])}，观看 {best['观看']:,}" if organic else f"CPL {C.money(best['CPL'])}，CTR {C.pct(best['CTR'])}") + '，n=1 版'
    rv.append({'回流ID': rid, '来源': src, '稿件ID': a.draft, '评审轮次': '投流复盘', '评审人': '（待专家确认）', '评审日期': datetime.date.today().isoformat(),
               '结论': f"{best['版本']} " + ('演练暂列第一（模拟，不作结论）' if a.sim else ('胜出' if ok else '暂定胜出')), '问题位置': '首图/版本', '问题类型': '投流效果' if not organic else '自然流量效果',
               '专家原话': '', '修改建议': '；'.join(f"{v['版本']}：{v['决策']}" for v in res), '回写目标': sid, '是否已回写': '否',
               '备注': ('【模拟】' if a.sim else '') + f'见 复盘_{a.draft}.md'})
    if not any(x['规则ID'] == sid for x in sl):
        sl.append({'规则ID': sid, '版本': 'v1.0', '维度': '投流复盘' if not organic else '自然流量复盘',
                   '规则': f"同类帖子优先用「{desc}」的做法（版本 {best['版本']} 胜出），其他做法只做小额对照。",
                   '必须做': f"下一篇把「{desc}」作为主版，另留一个只改一个变量的对照版继续测；按 {'收藏率' if organic else 'SL-G13'} 判定。",
                   '禁止做': '没过门槛就把本条当已验证规则。', '依据来源': f"{rid}；{ev}",
                   '状态': '提议·待专家确认' + ('（模拟，只能否决）' if a.sim else ''), '专家意见': '', '更新日期': datetime.date.today().isoformat()})
    C.save_table(p, '评审回流库', rv); C.save_table(p, '风格锁', sl); print('已写回（待专家确认）：', rid, sid)


def cmd_verdict(cfg, p, a):
    r = load_baseline(p, a.sim)
    if metric_of(r, a) == 'organic': return verdict_organic(cfg, p, a, r)
    tg = r['目标线']
    vs = [c for c in r['成绩单'] if c['帖子'].startswith(a.draft + '-')]
    if len(vs) < 2: sys.exit(f'成绩单里找不到 ≥2 个 {a.draft}-X 版本；检查计划命名或 投放映射.csv 的 关联样本ID')
    res = []
    for c in vs:
        v = dict(版本=c['帖子'].split('-', 1)[1] if '-' in c['帖子'] else c['帖子'], 帖子=c['帖子'], 计划=c['关联计划'],
                 消费=c['消费'], 展现=c['展现'], 点击=c['点击'], 留资=c['留资'])
        v.update(judge(v, tg)); res.append(v)
    best = decide(res); label = C.SIM_LABEL if a.sim else '真实数据'
    if a.sim: sim_safe(res)
    out_dir = os.path.join(p['sim'] if a.sim else p['root'], 'out'); os.makedirs(out_dir, exist_ok=True)
    o = dict(标注=label, 稿件=a.draft, 生成=f'{datetime.datetime.now():%Y-%m-%d %H:%M}', 目标线=tg, 结果=res,
             胜出=best['版本'] if best else None, 胜出已确认=bool(best and best['CPL过门槛']))
    C.dump_json(o, os.path.join(out_dir, f'复盘_{a.draft}.json'))
    L = [f'# 投流复盘 · {a.draft}（{label}）', '']
    if a.sim: L += ['> 模拟演练：数字来自历史计划“扮演”各版本，只用来走通复盘流程，**不能当作这篇的真实效果，也不能单凭它改规则**。', '']
    L += [f"目标线：CTR 及格 ≥ {C.pct(tg.get('CTR及格'))} / 优秀 ≥ {C.pct(tg.get('CTR优秀'))}；CPL 及格 ≤ {C.money(tg.get('CPL及格'))} / 优秀 ≤ {C.money(tg.get('CPL优秀'))}", '',
          '| 版本 | 消费 | 展现 | 点击 | CTR | 留资 | CPL | CTR判定 | CPL判定 | 决策 |', '|---|---|---|---|---|---|---|---|---|---|']
    L += [f"| {v['版本']} | {v['消费']:,.2f} | {v['展现']:,} | {v['点击']} | {C.pct(v['CTR'])} | {v['留资']} | {C.money(v['CPL'])} | {v['CTR判定']} | {v['CPL判定']} | {v['决策']} |" for v in res]
    none_msg = ('模拟数据里各版都是 0 留资：先核对留资列（juguang.lead_field）是否对上导出；模拟演练不下停投结论' if a.sim
                else '全部 0 留资，没有胜出版本；按止损规则换创意（先确认留资列 juguang.lead_field 对得上导出）')
    if a.sim and best: concl = '版本 ' + best['版本'] + ' 在演练里暂列第一（模拟数据，不能据此放量、停投或改规则）'
    else: concl = ('版本 ' + best['版本'] + (' 胜出（已过 CPL 门槛）' if best['CPL过门槛'] else ' 暂定胜出（未过 CPL 门槛，继续跑）')) if best else none_msg
    L += ['', f"**结论**：{concl}", '',
          ('**下一步**：这是演练，不动聚光里的任何计划。真实数据跑到门槛后，再由专家决定放量/停投和要不要写进风格锁（模拟产生的提议只能否决）。' if a.sim else
           '**下一步（人工关卡）**：专家看完这张表，决定 ①聚光里放量/停哪个计划（人工操作）②哪条规律写进风格锁。'),
          f'`--write-back` 会把结论写成评审回流（来源={"投放数据·模拟" if a.sim else "投放数据"}）和一条「提议·待专家确认」的风格锁规则；专家同意后运行 `ledger.py approve --id <规则ID>` 才生效。']
    md = os.path.join(out_dir, f'复盘_{a.draft}.md'); open(md, 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    render(cfg, o, os.path.join(out_dir, f'复盘_{a.draft}.png'), a.cover)
    print('\n'.join(L[-9 - len(res):-4])); print('输出：', md)
    if a.write_back and best: write_back(p, a, best, res)


def render(cfg, o, path, covers, organic=False):
    from PIL import Image, ImageDraw
    F = lambda s: C.font(cfg, 'body', s); dark = C.hex2rgb(C.get(cfg, 'brand.colors.dark'), (40, 40, 40))
    acc = C.hex2rgb(C.get(cfg, 'brand.colors.accent'), (230, 120, 30)); cov = dict(x.split('=', 1) for x in covers or [])
    n = len(o['结果']); W = max(1200, 420 * n + 100); img = Image.new('RGB', (W, 1500), (250, 248, 243)); d = ImageDraw.Draw(img); y = 30
    if o['标注'] != '真实数据':
        d.rectangle([0, 0, W, 70], fill=(200, 40, 40)); d.text((W / 2, 35), o['标注'], font=F(34), fill='white', anchor='mm'); y = 100
    d.text((50, y), f"{'自然流量复盘' if organic else '投流复盘'} · {o['稿件']}", font=F(48), fill=dark); y += 90; cw = (W - 100 - 20 * (n - 1)) // n
    for i, v in enumerate(o['结果']):
        x = 50 + i * (cw + 20); win = v['版本'] == o['胜出']
        d.rounded_rectangle([x, y, x + cw, y + 1150], 20, fill='white', outline=acc if win else (220, 214, 200), width=6 if win else 2)
        d.text((x + cw / 2, y + 20), f"版本 {v['版本']}" + (' ★' if win else ''), font=F(36), fill=acc if win else dark, anchor='ma'); yy = y + 80
        if cov.get(v['版本']) and os.path.exists(cov[v['版本']]):
            th = Image.open(cov[v['版本']]).convert('RGB'); tw = min(300, cw - 40); th = th.resize((tw, int(tw * th.height / th.width)))
            img.paste(th, (int(x + (cw - tw) / 2), yy)); yy += th.height + 20
        rows_ = ([('观看', f"{v['展现']:,}"), ('收藏', v['点击']), ('收藏率', f"{C.pct(v['CTR'])} {v['CTR判定']}"), ('互动率', f"{C.pct(v['互动率'])} {v['CPL判定']}"), ('咨询', v['留资'])]
                 if organic else [('消费', f"{v['消费']:,.0f}"), ('展现/点击', f"{v['展现']:,}/{v['点击']}"), ('CTR', f"{C.pct(v['CTR'])} {v['CTR判定']}"),
                       ('留资', v['留资']), ('CPL', C.money(v['CPL'])), ('CPL判定', v['CPL判定'])])
        for k, val in rows_:
            d.text((x + 20, yy), str(k), font=F(24), fill=(120, 120, 120)); yy += 32
            for ln in C.wrap_text(d, str(val), F(28), cw - 40): d.text((x + 20, yy), ln, font=F(28), fill=dark); yy += 38
            yy += 6
        for ln in C.wrap_text(d, '决策：' + v['决策'], F(26), cw - 40): d.text((x + 20, yy), ln, font=F(26), fill=acc if win else dark); yy += 36
    img.crop((0, 0, W, y + 1180)).save(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--config', default='config/brand.yaml'); ap.add_argument('--data', default='data')
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('baseline'); s.add_argument('--sim', action='store_true')
    s = sub.add_parser('plan'); s.add_argument('--draft', required=True); s.add_argument('--variant', action='append', default=[], help='版本=说明')
    s.add_argument('--budget', type=float); s.add_argument('--metric', choices=['paid', 'organic'])
    s = sub.add_parser('verdict'); s.add_argument('--draft', required=True); s.add_argument('--sim', action='store_true')
    s.add_argument('--metric', choices=['paid', 'organic']); s.add_argument('--write-back', action='store_true'); s.add_argument('--cover', action='append', help='版本=首图路径（复盘图里放缩略图）')
    a = ap.parse_args(); cfg = C.load_yaml(a.config); p = C.data_paths(a.data)
    {'baseline': cmd_baseline, 'plan': cmd_plan, 'verdict': cmd_verdict}[a.cmd](cfg, p, a)


if __name__ == '__main__':
    main()
