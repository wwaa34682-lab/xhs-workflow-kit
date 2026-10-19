#!/usr/bin/env python3
"""人工关卡的记账工具（第 6 步评审回流、风格锁生效、第 7 步发布队列）。agent 只在专家/用户明确说了之后才调用。

  # 记一条专家评审（原话照抄）
  python scripts/ledger.py --data data review --draft D001 --round 1 --verdict 不通过 --where P01 --type 排版 \
      --quote "像PPT" --suggest "改笔记感拼贴" --target SL-G04 --reviewer 张三
  # 把评审意见写回风格锁（新规则 or 改旧规则）；--from 关联评审行，自动标“已回写”
  python scripts/ledger.py --data data rule --id SL-B01 --dim 配色 --rule "..." --must "..." --ban "..." --from RV-D001-01 --status 生效·专家确认
  # 专家确认/否决一条“提议”规则（数据回收、复盘产生的都是提议）
  python scripts/ledger.py --data data approve --id SL-G14 --note "同意"     |  ... approve --id SL-G14 --reject --note "样本太少"
  # 模拟（SL-SIM-*）规则只能否决；否决/生效会同步关联的评审回流
  # 清掉挂着的“待回写”：python scripts/ledger.py --data data resolve --id RV-D001-03 --status 不需要 --note "专家：不用改规则"
  # 更新发布队列（状态：待审 / 不通过 / 已通过，待发布 / 已发布 / 投流中 / 已复盘）
  python scripts/ledger.py --data data queue --draft D001 --status 已发布 --note-id 64xxxxxxxx --link https://...
  # A/B 各版本（版本精确匹配，不会命中方案行 PQ-AB-D001）
  python scripts/ledger.py --data data queue --draft D001 --variant A --status 投流中
  # 受监管行业：合规审核人的结论单独记（不覆盖专家结论）；面向未成年人投流前再记一条 合规·投流
  python scripts/ledger.py --data data review --draft D001 --type 合规 --verdict 通过 --reviewer "校长" --quote "原话"
  # 风格锁规则写依据来源（样本ID / 数据结论）：rule ... --basis "BM-003、BM-007 都是满版作品照"

必问事实硬闸门：review --verdict 通过 要求 config/required_facts.yaml 的 gates.review 全部问清；
queue --status 已通过，待发布 / 已发布 / 投流中 / 已复盘 要求 gates.publish 全部问清。缺任何一项、或还是【待业务确认】，都拒绝并列出缺什么。
受监管行业（合规包 regulated: true）：已发布 / 投流中 还要求合规审核人（compliance.reviewer）的「合规」通过记录；
compliance.minor_audience 以“是”开头时，投流中 还要求一条「合规·投流」通过记录。
用 --config 指定 brand.yaml（默认 config/brand.yaml）。
"""
import argparse, datetime, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C
import facts as F


def fact_gate(a, name, what):
    if not os.path.exists(a.config):
        sys.exit(f'✗ 硬闸门：找不到 {a.config}，无法核对必问事实，不能{what}。用 --config 指定 brand.yaml。')
    miss = F.gate(C.load_yaml(a.config), name)
    if miss:
        lines = '\n'.join(f'  - 第{n}步 {f["key"]}：{F.ask_line(f)}' for n, f in miss)
        sys.exit(f'✗ 硬闸门：还有 {len(miss)} 项必问事实没问清，不能{what}：\n{lines}\n逐项问用户（一次一个），写进 brand.yaml 后再试。')

TODAY = datetime.date.today().isoformat()


def is_compliance(t):
    return str(t or '').startswith('合规')


def compliance_gate(p, a, status):
    """受监管行业：发布/投流前要有合规审核人（compliance.reviewer）记下的「合规」通过；面向未成年人时，投流前还要单独一条「合规·投流」。"""
    cfg = C.load_yaml(a.config); prof = C.load_profile(cfg)
    if not prof.get('regulated') or status not in ('已发布', '投流中'): return
    who = str(C.get(cfg, 'compliance.reviewer') or ''); rv = C.load_table(p, '评审回流库')
    def ok(kind):
        return any(r.get('稿件ID') == a.draft and r.get('结论') == '通过' and r.get('问题类型', '') == kind and
                   r.get('评审人') and (r['评审人'] in who or who.split('（')[0] in r['评审人']) for r in rv)
    if not ok('合规'):
        sys.exit(f'✗ 硬闸门（{prof["_id"]}行业）：{a.draft} 还没有合规审核人「{who or "未填"}」的合规通过记录，不能改成「{status}」。\n'
                 f'  合规审核人看过文案和图后：python scripts/ledger.py --data <data> --config <brand.yaml> review --draft {a.draft} --type 合规 --verdict 通过 --reviewer "<审核人>" --quote "原话"')
    if status == '投流中' and str(C.get(cfg, 'compliance.minor_audience') or '').startswith('是') and not ok('合规·投流'):
        sys.exit(f'✗ 硬闸门：课程面向未成年人，投流前合规审核人「{who}」要单独确认一次投流（定向、落地页、话术）。\n'
                 f'  确认后：python scripts/ledger.py ... review --draft {a.draft} --type 合规·投流 --verdict 通过 --reviewer "<审核人>" --quote "原话"')


def review(p, a):
    if a.verdict == '通过': fact_gate(a, 'review', '记录专家评审“通过”')
    rows = C.load_table(p, '评审回流库')
    n = sum(1 for r in rows if r.get('稿件ID') == a.draft) + 1
    rid = f'RV-{a.draft}-{n:02d}'
    rows.append({'回流ID': rid, '来源': a.source, '稿件ID': a.draft, '评审轮次': a.round, '评审人': a.reviewer, '评审日期': TODAY,
                 '评分(1-10)': a.score or '', '结论': a.verdict, '问题位置': a.where, '问题类型': a.type, '专家原话': a.quote,
                 '修改建议': a.suggest, '回写目标': a.target, '是否已回写': '不需要' if a.verdict == '通过' and not a.target else '否',
                 '备注': a.memo or ''})
    C.save_table(p, '评审回流库', rows); print('已记', rid)
    q = C.load_table(p, '发布队列')
    if is_compliance(a.type):   # 合规审核单独记，不覆盖专家结论；不通过时把稿件打回
        if a.verdict != '通过':
            for r in q:
                if r.get('稿件ID') == a.draft and not r.get('队列ID', '').startswith('PQ-AB'): r['状态'] = '不通过'; r['待确认事项'] = '合规审核不通过：' + (a.quote or '')
            C.save_table(p, '发布队列', q)
        return
    for r in q:
        if r.get('稿件ID') == a.draft:
            r['评审轮次'] = a.round; r['专家结论'] = a.verdict
            r['状态'] = '已通过，待发布' if a.verdict == '通过' else ('不通过' if a.verdict == '不通过' else '待审')
    C.save_table(p, '发布队列', q)


def rule(p, a):
    rows = C.load_table(p, '风格锁'); cur = next((r for r in rows if r['规则ID'] == a.id), None)
    if cur is None:
        cur = {'规则ID': a.id, '版本': 'v1.0'}; rows.append(cur)
    else:
        v = cur.get('版本', 'v1.0').lstrip('v'); cur['版本'] = 'v' + (f'{float(v) + 0.1:.1f}' if v.replace('.', '').isdigit() else '1.1')
    for k, v in (('维度', a.dim), ('规则', a.rule), ('必须做', a.must), ('禁止做', a.ban), ('状态', a.status), ('专家意见', a.note)):
        if v is not None: cur[k] = v
    if a.__dict__.get('from') or a.basis:
        cur['依据来源'] = '；'.join(x for x in [cur.get('依据来源', ''), a.__dict__.get('from') or '', a.basis or ''] if x)
    cur['更新日期'] = TODAY; C.save_table(p, '风格锁', rows)
    if a.__dict__.get('from'):
        rv = C.load_table(p, '评审回流库'); ids = a.__dict__['from'].replace('，', ',').split(',')
        for r in rv:
            if r['回流ID'] in ids: r['是否已回写'] = '是'; r['回写后版本'] = f"{a.id} {cur['版本']}"
        C.save_table(p, '评审回流库', rv)
    print('风格锁', a.id, cur['版本'], cur.get('状态'))


def approve(p, a):
    rows = C.load_table(p, '风格锁'); r = next((r for r in rows if r['规则ID'] == a.id), None)
    if r is None: sys.exit(f'风格锁里没有 {a.id}')
    sim = a.id.startswith('SL-SIM-') or '模拟' in (r.get('状态', '') + r.get('依据来源', ''))
    if sim and not a.reject:
        sys.exit(f'✗ 铁律：{a.id} 来自模拟数据，只能否决（--reject），不能生效。拿到真实投放数据后，用 ab_test.py verdict --write-back 重新生成提议。')
    r['状态'] = '已否决' if a.reject else '生效·专家确认'; r['专家意见'] = a.note or r.get('专家意见', ''); r['更新日期'] = TODAY
    C.save_table(p, '风格锁', rows); print(a.id, '→', r['状态'])
    # 关联的评审回流同步：否决 → 不需要回写；生效 → 已回写
    rv = C.load_table(p, '评审回流库'); n = 0
    for x in rv:
        if x.get('回写目标') == a.id and x.get('是否已回写') not in ('是', '不需要'):
            x['是否已回写'] = '不需要' if a.reject else '是'; x['回写后版本'] = '' if a.reject else f"{a.id} {r.get('版本', '')}"
            x['备注'] = '；'.join(v for v in [x.get('备注', ''), f'{TODAY} 规则{"已否决" if a.reject else "已生效"}'] if v); n += 1
    if n: C.save_table(p, '评审回流库', rv); print(f'同步了 {n} 条评审回流')


def resolve(p, a):
    """把挂着“待回写”的评审回流标成 是 / 不需要（例如专家说这条不用改规则）。"""
    rv = C.load_table(p, '评审回流库'); ids = set(a.id.replace('，', ',').split(',')) if a.id != 'all-sim' else None
    n = 0
    for x in rv:
        hit = (x['回流ID'] in ids) if ids else ('模拟' in x.get('来源', '') and x.get('是否已回写') not in ('是', '不需要'))
        if hit:
            x['是否已回写'] = a.status; x['备注'] = '；'.join(v for v in [x.get('备注', ''), a.note or ''] if v); n += 1
    C.save_table(p, '评审回流库', rv); print(f'已更新 {n} 条评审回流 → {a.status}')


def queue(p, a):
    if a.status in ('已通过，待发布', '已发布', '投流中', '已复盘'): fact_gate(a, 'publish', f'改成「{a.status}」')
    if a.status: compliance_gate(p, a, a.status)
    rows = C.load_table(p, '发布队列')
    # 版本精确匹配（"A" 不会命中 "A / B"），并跳过 ab_test.py 写的方案行 PQ-AB-*
    ver = lambda r: (r.get('版本或套系', '').split() or [''])[0]
    r = next((r for r in rows if r.get('稿件ID') == a.draft and not r.get('队列ID', '').startswith('PQ-AB') and
              (ver(r) == a.variant if a.variant else True)), None)
    if r is None:
        r = {'队列ID': f'PQ-{len(rows) + 1:03d}', '稿件ID': a.draft}
        base = next((x for x in rows if x.get('稿件ID') == a.draft and not x.get('队列ID', '').startswith('PQ-AB')), None)
        if base and a.variant:   # 同一稿件的 A/B 版本：继承这篇的评审结论（评审是按稿件过的）
            for k in ('账号', '标题', '稿件路径', '评审轮次', '专家结论', '含AI内容'): r[k] = base.get(k, '')
        rows.append(r)
    if a.status in ('已通过，待发布', '已发布', '投流中') and r.get('专家结论') != '通过':
        sys.exit(f'人工关卡：{a.draft} 的专家结论还不是「通过」，不能改成「{a.status}」。先用 review 记录专家结论。')
    m = {'状态': a.status, '标题': a.title, '账号': a.account, '稿件路径': a.path, '图片数': a.images, '版本或套系': a.variant,
         '含AI内容': a.ai, '计划发布时间': a.plan_time, '笔记ID': a.note_id, '笔记链接': a.link, '是否投流': a.boost,
         '关联投流计划': a.plans, '投流目标': a.goal, '待确认事项': a.todo, '备注': a.memo}
    for k, v in m.items():
        if v is not None: r[k] = v
    if a.status == '已发布' and not r.get('实际发布时间'): r['实际发布时间'] = TODAY
    C.save_table(p, '发布队列', rows); print('发布队列', r['队列ID'], r.get('状态'))
    if r.get('含AI内容') == '是': print('提醒：发布时在小红书勾选「含AI生成内容」。')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--data', default='data'); ap.add_argument('--config', default='config/brand.yaml', help='brand.yaml（硬闸门核对必问事实）')
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('review'); s.add_argument('--draft', required=True); s.add_argument('--round', default='1')
    s.add_argument('--verdict', required=True, choices=['通过', '不通过', '修改后再审']); s.add_argument('--where', default='全部')
    s.add_argument('--type', default='', help='问题类型；合规审核用「合规」，面向未成年人投流前用「合规·投流」'); s.add_argument('--quote', default='', help='专家原话，照抄'); s.add_argument('--suggest', default='')
    s.add_argument('--target', default='', help='要回写的风格锁规则ID'); s.add_argument('--reviewer', default='专家'); s.add_argument('--score')
    s.add_argument('--source', default='专家评审', help='专家评审 / 投放数据 / 投放数据·模拟'); s.add_argument('--memo')
    s = sub.add_parser('rule'); s.add_argument('--id', required=True)
    for k in ('dim', 'rule', 'must', 'ban', 'note'): s.add_argument('--' + k)
    s.add_argument('--status', default='生效·专家确认'); s.add_argument('--from', dest='from', help='评审回流ID，逗号分隔')
    s.add_argument('--basis', help='依据来源（样本ID、数据结论等），如 "BM-003、BM-007 都是满版作品照"')
    s = sub.add_parser('approve'); s.add_argument('--id', required=True); s.add_argument('--reject', action='store_true'); s.add_argument('--note')
    s = sub.add_parser('resolve', help='把待回写的评审回流标成 是/不需要'); s.add_argument('--id', required=True, help='回流ID，逗号分隔；all-sim = 全部模拟来源的')
    s.add_argument('--status', default='不需要', choices=['是', '不需要']); s.add_argument('--note')
    s = sub.add_parser('queue'); s.add_argument('--draft', required=True); s.add_argument('--status')
    for k in ('title', 'account', 'path', 'images', 'variant', 'ai', 'plan-time', 'note-id', 'link', 'boost', 'plans', 'goal', 'todo', 'memo'):
        s.add_argument('--' + k)
    a = ap.parse_args(); p = C.data_paths(a.data)
    {'review': review, 'rule': rule, 'approve': approve, 'resolve': resolve, 'queue': queue}[a.cmd](p, a)


if __name__ == '__main__':
    main()
