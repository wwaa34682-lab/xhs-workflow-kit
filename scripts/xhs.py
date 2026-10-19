#!/usr/bin/env python3
"""一条命令知道现在在哪：
  python scripts/xhs.py status       3 行：当前步骤 / 待办 / 下一步（说给用户听）
  python scripts/xhs.py next         3 行：agent 要做什么 / 命令 / 读哪个步骤文件
  python scripts/xhs.py quickstart   快速起步：用已确认的 5 项事实 + 参考图做出第一篇草稿首图（约 10 分钟）
                                     没有参考图时，用户二次确认后加 --no-reference-confirmed
  python scripts/xhs.py card         确认卡：把这一步还缺的事实一次列出来（已从用户原话里知道的先填好），用户一次核对
                                     预填来自 <data>/facts_draft.yaml（只能写用户亲口说过的话，带原话出处）
  python scripts/xhs.py new          开下一篇稿件（D002…）：沿用已确认的事实；--reuse-refs 沿用上一篇的参考图
可选参数：--data data --config config/brand.yaml [--draft D001]
本脚本只读状态、搭草稿骨架，并调用现有的 check_copy.py / render_post.py；不改任何产出逻辑和质量闸门。"""
import argparse, glob, os, shutil, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C
import facts as F

S = lambda n: os.path.join(C.KIT, 'scripts', n)
NAMES = {0: '建档', 1: '对标帖拆解', 2: '自有帖拆解', 3: '风格锁', 4: '出文案', 5: '出图', 6: '专家评审',
         7: '发布', 8: '数据回收', 9: '投流AB方案', 10: '投流复盘'}
STEPFILE = {0: 'onboarding/开始使用.md', 1: 'steps/01-对标帖拆解.md', 2: 'steps/02-自有帖拆解.md', 3: 'steps/03-风格锁.md',
            4: 'steps/04-出文案.md', 5: 'steps/05-选模板与出图.md', 6: 'steps/06-专家评审与回流.md', 7: 'steps/07-发布队列.md',
            8: 'steps/08-数据回收.md', 9: 'steps/09-投流AB方案.md', 10: 'steps/10-投流复盘与回写.md'}


def unknown_paths(o, pre=''):
    if isinstance(o, dict): return [x for k, v in o.items() for x in unknown_paths(v, f'{pre}{k}.')]
    if isinstance(o, list): return [x for i, v in enumerate(o) for x in unknown_paths(v, f'{pre}{i}.')]
    return [pre.rstrip('.')] if C.UNKNOWN in str(o) else []


def tag(n, extra=''):
    return '快速起步' if n == 'Q' else f'第{n}/10步·{NAMES[n]}{extra}'


CHOICE = '出图前二选一：1.【推荐·默认】给参考图，做针对性修改（发我 1 张以上你觉得好看的图）2. 没有参考图（极度不推荐）'
PHOTO_ASK = {'cover_photo': '这个版式还要 1 张你们自己的作品/门店实拍做首图背景（竖图、清晰、有授权）',
             'cover_subject': '这个版式还要 1 张产品照（最好是透明底抠图 PNG；普通照片我先帮你抠）'}


def layout_of(cfgp):
    lay = os.path.join(os.path.dirname(cfgp), 'layout.yaml')
    return C.load_yaml(lay) if os.path.exists(lay) else {}


def choice(cfgp, d=None):
    """出图方式二选一；版式需要用户照片时，同一句里顺便要照片（不多问一轮）。"""
    from render_post import needs_photo
    need = needs_photo(layout_of(cfgp))
    pg = C.load_yaml(os.path.join(d, 'pages.yaml')) if d and os.path.exists(os.path.join(d, 'pages.yaml')) else {}
    return CHOICE + (f'。另外：{PHOTO_ASK[need]}' if need and not pg.get(need) else '')


def pages_of(d):
    f = os.path.join(d, 'pages.yaml')
    return C.load_yaml(f) if os.path.exists(f) else {}


def missing_photos(cfgp, d):
    """首图照片 + 内页照片里找不到文件的（路径相对稿件目录）。"""
    from render_post import needs_photo
    pg = pages_of(d); out = []
    def found(x):
        return any(os.path.exists(os.path.join(b, os.path.expanduser(str(x)))) for b in (d, os.path.dirname(os.path.dirname(d)), os.getcwd(), C.KIT)) or os.path.isabs(str(x)) and os.path.exists(str(x))
    need = needs_photo(layout_of(cfgp))
    if need:
        v = pg.get(need) or ((layout_of(cfgp).get('cover') or {}).get('background' if need == 'cover_photo' else 'subject') or {}).get('path')
        if not v or not found(v): out.append('首图' + ('照片' if need == 'cover_photo' else '产品图'))
    for i, page in enumerate(pg.get('inner') or [], start=2):
        phs = page.get('photos') or ([page['photo']] if page.get('photo') else [])
        for ph in phs:
            lab = f'P{i:02d}「{page.get("photo_label") if len(phs) == 1 and page.get("photo_label") else os.path.basename(str(ph))}」'
            if not found(ph) and lab not in out: out.append(lab)
    return out


def is_first(drafts, d):
    return not drafts or os.path.abspath(d) == os.path.abspath(drafts[0])


def preset_for(cfg):
    prof = str(C.get(cfg, 'compliance.profile') or ''); ind = str(C.get(cfg, 'industry') or '')
    if prof in ('医疗', '医美', '金融'): return '极简大标题'
    if prof == '餐饮食品' or any(k in ind for k in ('餐', '咖啡', '茶', '零售', '食品', '烘焙', '面', '饮')): return '产品主体'
    if any(k in ind for k in ('美', '健身', '瑜伽', '普拉提', '教育', '培训', '本地', '摄影', '亲子')): return '照片满版'
    return '极简大标题'


def ref_problems(cfgp, root, did):
    lay = os.path.join(os.path.dirname(cfgp), 'layout.yaml')
    if not os.path.exists(lay): return ['还没有 config/layout.yaml']
    from render_post import reference_problems
    return reference_problems(C.load_yaml(lay), os.path.join(root, 'refs', did))


def copy_ok(cfg_path, d):
    cp = os.path.join(d, 'copy.md')
    if not os.path.exists(cp) or '待撰写' in open(cp, encoding='utf-8').read(): return None
    args = [sys.executable, S('check_copy.py'), '--config', cfg_path, '--copy', cp]
    if os.path.exists(os.path.join(d, 'pages.yaml')): args += ['--pages', os.path.join(d, 'pages.yaml')]
    return subprocess.run(args, capture_output=True, text=True).returncode == 0


def state(a):
    """返回 (步骤号或'Q', 待办, 给用户的下一步, agent动作, 命令)。按 10 步顺序找第一个没完成的。"""
    cfgp, data = a.config, a.data
    D = f'--data {data}'; CF = f'--config {cfgp}'
    if not os.path.exists(cfgp):
        return 0, '还没有品牌档案', '回答 5 个问题（行业和品牌、卖什么和价格、在哪/门店、目标顾客、有没有聚光；共 9 项事实，合并在 5 问里），约 3 分钟',\
            '按快速通道一次问一个问题，写进 config/brand.yaml', 'cp config/brand.example.yaml ' + cfgp
    cfg = C.load_yaml(cfgp); unk = unknown_paths(cfg)
    def ask(n, miss, hard=False):
        names = '、'.join(F.label(f) for _, f in miss)
        head = (f'✗ 硬闸门：还有 {len(miss)} 项必问事实没问清，不能{"评审通过" if n == 6 else "发布"}：' if hard else f'这一步要先问清 {len(miss)} 项：') + names
        if len(miss) >= 2 and n != 0:   # 一步里缺 2 项以上：发一张确认卡一次核对（已知的先填好），不要连问多轮
            return (n, head, f'我把这 {len(miss)} 项列成一张确认卡（你说过的我已经填好），你一次核对就行',
                    f'运行 xhs.py card --step {n} 生成确认卡原样发给用户；用户核对后把答案（照抄原话）写进 brand.yaml', f'python scripts/xhs.py card --step {n} {D} {CF}', ex)
        return (n, head, '问：' + F.ask_line(miss[0][1]), f'按 docs/交互规范.md 一次只问一个（带选项、不给默认、答得含糊要追问），写进 brand.yaml 的 {miss[0][1]["key"]}', '（问答，无命令）', ex)
    ex = ''
    m0 = F.missing(cfg, [0])
    if m0: return ask(0, m0)
    p = C.data_paths(data)
    init = f'python scripts/build_tables.py {D} {CF} --init'
    if not os.path.exists(p['tables']):
        return 'Q', '资产表还没建', '我先建表并做第一篇草稿首图，你等我约 1 分钟', '建表后运行快速起步', f'{init} && python scripts/xhs.py quickstart'
    drafts = sorted(d for d in glob.glob(os.path.join(p['drafts'], '*')) if os.path.isdir(d))
    if not drafts:
        return 'Q', '还没有任何草稿', '我先用你确认的事实做第一篇草稿首图给你看', '运行快速起步', 'python scripts/xhs.py quickstart'
    for d in drafts[:1]:   # 只有第一篇是“快速起步”；第二篇起按正常步骤走（进度标签不再显示快速起步）
        cp = os.path.join(d, 'copy.md')
        if os.path.exists(cp) and '快速起步草稿' in open(cp, encoding='utf-8').read() and '待撰写' in open(cp, encoding='utf-8').read():
            if not os.path.exists(os.path.join(d, 'out', 'P01.png')):
                return 'Q', f'{os.path.basename(d)} 草稿已建，等你选出图方式', choice(cfgp, d), \
                    '按 steps/05 让用户二选一，登记参考图（或二次确认）后再运行快速起步', 'python scripts/xhs.py quickstart'
            return 'Q', f'{os.path.basename(d)} 首图已出，文案还没写', '我在写这篇的文案，写完把首图和文案一起给你看', \
                '按 steps/04 和风格锁改写 copy.md、pages.yaml 的标题，再运行快速起步做校验', 'python scripts/xhs.py quickstart'
    T = lambda n: C.load_table(p, n)
    posts = T('爆款样本库_样本帖子'); imgs = T('爆款样本库_样本图片')
    todo = lambda kind: sum(1 for r in posts + imgs if r.get('样本ID', '').startswith(kind) for v in r.values() if C.TODO in str(v))
    inbox = lambda k: [f for f in glob.glob(os.path.join(p['root'], 'inbox', k, '*')) if os.path.isdir(f) and not os.path.exists(os.path.join(f, '.ingested'))]
    ing = f'python scripts/ingest_posts.py {D}'
    if not posts and F.missing(cfg, [1]): return ask(1, F.missing(cfg, [1]))
    for n, kind, k, what in ((1, 'BM-', 'bench', '对标帖'), (2, 'OWN-', 'own', '自有帖')):
        if inbox(k):
            return n, f'收件箱有 {len(inbox(k))} 篇{what}未入库', '我先把它们入库，不需要你操作', '入库', ing
        if not any(r.get('样本ID', '').startswith(kind) for r in posts):
            mode = C.get(cfg, 'collection.mode')
            how = '把 5–20 篇' + what + '的截图和正文发给我' if mode != 'browser' else '准备好研究小号，登录时需要你在场'
            return n, f'还没有{what}', how, f'按 {STEPFILE[n]} 收集到 data/inbox/{k}/', ing
        if todo(kind):
            return n, f'{what}还有 {todo(kind)} 格【待拆解】', '我在拆解，不需要你操作，完成后给你看结论', \
                '按 templates/拆解模板.md 填完【待拆解】', f'python scripts/build_tables.py {D} {CF}'
    locks = T('风格锁')
    if not locks:
        return 3, '风格锁是空的', '我根据拆解结论起草规则，请专家确认', '按 steps/03 起草规则', 'python scripts/ledger.py rule --id ...'
    d = drafts[-1]; did = os.path.basename(d); ex = f'（{did}）'
    ok = copy_ok(cfgp, d)
    if F.missing(cfg, [4]): return ask(4, F.missing(cfg, [4]))   # 快速起步的文案即使校验通过，第 4 步的事实也要问齐
    if ok is None:
        return (4, '稿件还没有文案', '我在写文案，写完给你看', '按 steps/04 写 copy.md', f'python scripts/check_copy.py {CF} --copy {d}/copy.md --pages {d}/pages.yaml', ex)
    if ok is False:
        return (4, '文案校验没通过', '我按校验结果修改文案，不需要你操作', '修改 copy.md 直到校验 0 个必须改', f'python scripts/check_copy.py {CF} --copy {d}/copy.md --pages {d}/pages.yaml', ex)
    if not str(pages_of(d).get('copy_confirmed') or '').strip():
        return (4, '标题、正文、标签等你确认', '我把标题备选、正文、标签原样发你：挑一个标题，正文和标签有要改的直接说',
                '把 copy.md 的标题备选、正文、标签原样发给用户；用户确认后把原话写进 pages.yaml 的 copy_confirmed（改了就先改再确认）', '（问用户）', ex)
    lay = os.path.join(os.path.dirname(cfgp), 'layout.yaml')
    if not os.path.exists(os.path.join(d, 'out', 'P01.png')) and F.missing(cfg, [5]): return ask(5, F.missing(cfg, [5]))
    noref_ok = any(r.get('稿件ID') == did and r.get('问题类型') == '缺参考图' for r in T('评审回流库'))
    if not os.path.exists(os.path.join(d, 'out', 'P01.png')) and ref_problems(cfgp, p['root'], did) and not noref_ok:
        reuse = '（第二篇起：回“1”就沿用上一篇的参考图，也可以发新图）' if not is_first(drafts, d) else ''
        return (5, '还没登记参考图（硬规则：没有参考图不出图）', choice(cfgp, d) + reuse, '按 steps/05 让用户二选一；选 1 就登记参考图并按 templates/参考图拆解清单.md 写进 layout.yaml', f'（问用户；登记后）python scripts/render_post.py {CF} --layout {lay} --draft {d}', ex)
    render = f'python scripts/render_post.py {CF} --layout {lay} --draft {d}'
    if not os.path.exists(os.path.join(d, 'out', 'P01.png')):
        return (5, '还没出图', '我在出图，做完给你看预览', '按 steps/05 出首图和内页', render, ex)
    # 第 5 步完成的标准：首图 + 内页都出了、照片齐、人脸按规则处理过、给用户看过参考对比（快速起步只出了首图，不算完成）
    pg = pages_of(d); inner = pg.get('inner') or []
    if F.missing(cfg, [5]): return ask(5, F.missing(cfg, [5]))
    if not inner:
        return (5, '只有首图，内页还没做', '我在做内页（3–5 张），做完和首图一起给你看', '按 steps/05 第 4 条在 pages.yaml 写 inner（3–5 页），再渲染全套', render, ex)
    holes = missing_photos(cfgp, d)
    if holes:
        return (5, f'缺 {len(holes)} 张照片：' + '、'.join(holes[:4]), f'请发 {len(holes)} 张你们自己的实拍（有授权），分别用在：' + '、'.join(holes[:4]),
                '收到照片后放进稿件目录，pages.yaml 引用；首图照片写 cover_photo（按稿件，不改全局 layout.yaml）', render, ex)
    if any(not os.path.exists(os.path.join(d, 'out', f'P{i:02d}.png')) for i in range(2, len(inner) + 2)):
        return (5, '内页还没出图', '我在出内页，做完给你看预览', '渲染全套（首图 + 内页）', render, ex)
    if not str(pg.get('faces') or '').strip():
        return (5, '照片里的人脸还没按规则核对', '我在按你定的人脸规则检查每张照片，不需要你操作',
                f'逐张看照片，按 face_policy（{C.get(cfg, "face_policy.mode")}）处理（scripts/face_swap.py），在 pages.yaml 写 faces: "<处理结果，如 无人脸 / P03 已打码 / 店主本人已授权>"，处理过的重新渲染', render, ex)
    if not ref_problems(cfgp, p['root'], did) and not str(pg.get('reference_feedback') or '').strip():
        return (5, '还没给你看「参考图 | 成品」对比', '我把参考图和成品并排给你看，你说哪里还要改（满意就回“可以”）',
                '把 out/参考对比.png 发给用户，写保留了/改成了各 3 条以内；用户原话写进 pages.yaml 的 reference_feedback，有修改意见就追加 reference.iterations 重出', render, ex)
    q = [r for r in T('发布队列') if r.get('稿件ID') == did]
    st = q[-1].get('状态', '') if q else ''
    lock_prop = [r['规则ID'] for r in locks if r.get('状态', '').startswith('提议')]
    if st in ('', '待审', '不通过') and F.gate(cfg, 'review'): return ask(6, F.gate(cfg, 'review'), hard=True)
    if st.startswith('已通过') and F.gate(cfg, 'publish'): return ask(7, F.gate(cfg, 'publish'), hard=True)
    if st in ('', '待审', '不通过'):
        who = C.get(cfg, 'reviewer.name'); who = '专家' if C.is_unknown(who) else who
        noref = any(r.get('稿件ID') == did and r.get('问题类型') == '缺参考图' for r in T('评审回流库'))
        if noref:
            return (6, '这篇是没有参考图的通用版，送审前再要一次参考图', '1. 给参考图，我按它重做（推荐）2. 就用这版送审', '按 steps/06 的“补参考图提醒”问用户', '（问用户）', ex)
        return (6, '等专家评审（人工关卡）', f'请{who}看图和文案：1. 通过 2. 修改后再审', '把专家原话记进评审回流库', f'python scripts/ledger.py {D} review --draft {did} --verdict ... --quote "原话"', ex)
    if st.startswith('已通过'):
        return (7, '等你发布（人工关卡）', '请你在小红书发布，发完把笔记链接贴给我', '登记笔记ID', f'python scripts/ledger.py {D} queue --draft {did} --status 已发布 --note-id ...', ex)
    has_jg = C.get(cfg, 'juguang.has') is True
    if F.missing(cfg, [8]): return ask(8, F.missing(cfg, [8]))
    if has_jg and not T('投放效果库') or not has_jg and not T('自然流量库'):
        src = '聚光“计划列表”和“创意数据”的 CSV' if has_jg else '创作者中心的笔记数据（没有聚光也能判效果：看收藏率）'
        how = f'python scripts/recover_juguang.py {CF} {D} --plan ... --creative ...' if has_jg else f'python scripts/recover_juguang.py {CF} {D} --organic <笔记数据.csv>'
        return (8, '还没有回收数据', f'帖子发出 3–7 天后，导出{src}发给我', '回收数据', how, ex)
    if not os.path.exists(os.path.join(p['out'], f'投流方案_{did}.md')):
        if not has_jg:
            return (9, '还没有 A/B 方案（自然流量版）', '我做好“轮流发两版”的方案给你看，你按顺序亲自发', '按 steps/09 的“没有聚光时”做方案', f'python scripts/ab_test.py {CF} {D} plan --draft {did} --variant A=... --variant B=...', ex)
        return (9, '还没有投流 A/B 方案', '我做好方案后给你看预算，请你拍板', '按 steps/09 做方案', f'python scripts/ab_test.py {CF} {D} plan --draft {did} --variant A=... --budget ...', ex)
    if not os.path.exists(os.path.join(p['out'], f'复盘_{did}.json')) and not os.path.exists(os.path.join(p['sim'], 'out', f'复盘_{did}.json')):
        if not has_jg:
            return (9, '方案已出，等你按顺序发 A、B 两版（人工关卡：发布由你操作）', '每发一版把笔记链接贴给我；都发完 7 天后导出笔记数据给我', '登记各版本笔记ID，等导出', f'python scripts/ledger.py {D} {CF} queue --draft {did} --variant A --status 已发布 --note-id ...', ex)
        return (9, '方案已出，等投流（人工关卡：预算和建计划由你操作）', '在聚光按方案建计划；跑完把导出发给我', '等导出后进入第 10 步', f'python scripts/ab_test.py {CF} {D} verdict --draft {did}', ex)
    if lock_prop:
        return (10, f'{len(lock_prop)} 条风格锁提议等专家确认（人工关卡）', '请专家确认这些新规则：1. 同意 2. 不同意', '记录专家结论', f'python scripts/ledger.py {D} approve --id {lock_prop[0]}', ex)
    unk = [k for k in unk if not F.irrelevant(cfg, k)]
    left = f'；还有 {len(unk)} 项【待业务确认】' if unk else ''
    return (10, '本篇闭环完成' + left, '下一篇：回复“继续”开始新稿件（已确认的事实、参考图、帖子类型都可以沿用）', '开下一篇稿件，回到第 4 步', f'python scripts/xhs.py new {D} {CF} --reuse-refs', ex)


def quickstart(a):
    cfgp = a.config
    if not os.path.exists(cfgp): sys.exit('还没有 brand.yaml：先按 onboarding/开始使用.md 的快速通道问 5 个问题')
    p = C.data_paths(a.data)
    if not os.path.exists(p['tables']):
        subprocess.run([sys.executable, S('build_tables.py'), '--data', a.data, '--config', cfgp, '--init'], capture_output=True)
    drafts = sorted(x for x in glob.glob(os.path.join(p['drafts'], '*')) if os.path.isdir(x))
    if drafts and os.path.basename(drafts[0]) != a.draft and not os.path.isdir(os.path.join(p['drafts'], a.draft)):
        sys.exit(f'快速起步只用于第一篇。开下一篇请用：python scripts/xhs.py new --data {a.data} --config {cfgp} --reuse-refs')
    cfg = C.load_yaml(cfgp)
    lay = os.path.join(os.path.dirname(cfgp), 'layout.yaml')
    if not os.path.exists(lay):
        pre = a.preset or preset_for(cfg)
        shutil.copy(os.path.join(C.KIT, 'config', 'layouts', pre + '.yaml'), lay)
        print(f'出图预设：{pre}（按行业推荐；看过参考图后可以换，见 config/layouts/README.md）')
    d = os.path.join(p['drafts'], a.draft); os.makedirs(d, exist_ok=True)
    for f in ('pages.yaml', 'copy.md'):
        if not os.path.exists(os.path.join(d, f)):
            shutil.copy(os.path.join(C.TPL, '快速起步', f), os.path.join(d, f))
            if f == 'pages.yaml':
                t = open(os.path.join(d, f), encoding='utf-8').read()
                if len(cfg.get('locations') or []) == 1:   # 单店不写“1 家门店可约”
                    t = t.replace('"{city} · {locations_count} 家门店可约"', '"{city} · {locations.0.name}"')
                if not C.is_unknown(C.get(cfg, 'content_rules.comment_keyword')):   # 关键词问过了才放 CTA，草稿上不出现【待业务确认】
                    t = t.replace('cta: ""   # 评论关键词在第 4 步确认后再加', 'cta: "评论区扣「{content_rules.comment_keyword}」"')
                open(os.path.join(d, f), 'w', encoding='utf-8').write(t)
    from render_post import needs_photo
    need = needs_photo(C.load_yaml(lay)); pg = pages_of(d)
    if ref_problems(cfgp, p['root'], a.draft) and not a.no_reference_confirmed:
        print(f'快速起步：草稿 {a.draft} 已建好，出图前要先选方式（硬规则）')
        print('问用户：' + choice(cfgp, d))
        print(f'选 1：参考图放进 {os.path.join(p["root"], "refs", a.draft)}/，按 templates/参考图拆解清单.md 填 layout.yaml 的 reference，再运行一次；选 2：先警告“没有参考图做出来的图片审美会非常差”，二次确认后加 --no-reference-confirmed')
        if need: print(f'照片：用户发来后存进 {d}/，在 pages.yaml 写 {need}: <文件名>（按稿件存，不改全局 layout.yaml）')
        return
    if need and any(x.startswith('首图') for x in missing_photos(cfgp, d)):
        print(f'⚠ 缺照片：{PHOTO_ASK[need]}。没有它首图会是一块纯色底——先向用户要（存进 {d}/，pages.yaml 写 {need}: <文件名>），拿到再运行一次')
        if not a.allow_blank: return
    cmd = [sys.executable, S('render_post.py'), '--config', cfgp, '--layout', lay, '--draft', d, '--only', 'cover']
    r = subprocess.run(cmd + (['--no-reference-confirmed'] if a.no_reference_confirmed else []), capture_output=True, text=True)
    if r.returncode: sys.exit('出图失败：\n' + r.stderr[-800:])
    warn = [l for l in r.stderr.splitlines() if l.strip() and not l.startswith('[字体]')]
    for l in warn: print('  ' + l)          # 出图警告原样透传（缺照片、文字缩小、路线重叠……）
    miss = [l for l in r.stderr.splitlines() if '没确认' in l]
    ok = copy_ok(cfgp, d)
    print(f'快速起步：首图 {os.path.join(d, "out", "P01.png")}')
    print('文案：' + ('还没写（agent 按 steps/04 改写 copy.md 后再运行一次）' if ok is None else '校验通过' if ok else '校验有必须改的问题，运行 check_copy.py 看明细'))
    print('待确认：' + (miss[0].lstrip('⚠ ') if miss else '无，图上事实都已确认') + '。')
    print('这只是首图草稿：接下来还要做内页、按人脸规则处理照片、给用户看「参考图 | 成品」对比（第 5 步），然后才进评审。运行 xhs.py next 看下一步')


def card(a):
    """确认卡：一步里缺的事实一次列出来。预填只能来自用户亲口说过的话（facts_draft.yaml 里带原话出处），没有出处的留空让用户填。"""
    cfg = C.load_yaml(a.config)
    n = a.step if a.step is not None else state(a)[0]
    n = 4 if n == 'Q' else int(n)
    miss = F.missing(cfg, [n])
    if not miss: print(f'第{n}步的必问事实都齐了，不用发确认卡'); return
    pf = a.prefill or os.path.join(a.data, 'facts_draft.yaml')
    pre = C.load_yaml(pf) if os.path.exists(pf) else {}
    prof = C.load_profile(cfg)
    banned = list(dict.fromkeys((C.get(cfg, 'content_rules.banned_words', []) or []) + [w for w in prof.get('banned') or [] if not str(w).startswith('re:')]))
    L = [f'【第{n}/10步·{NAMES[n]}】开始前帮我核对这 {len(miss)} 项' + ('（会印在图上或写进正文）' if n == 4 else '') + '：', '']
    blank = 0
    for i, (_, f) in enumerate(miss, 1):
        c = pre.get(f['key']); val = c.get('value') if isinstance(c, dict) else c; src = c.get('source') if isinstance(c, dict) else ''
        name = F.label(f).replace('<列出 banned_words>', '、'.join(banned[:12]))
        if f['key'] == 'content_rules.banned_words_confirmed':
            L.append(f'{i}. 不能说的词：{"、".join(banned[:12])}{"…" if len(banned) > 12 else ""} → 还要加吗？（1. 就这些 2. 再加：___）'); continue
        if val not in (None, '', []) and src:
            v = '、'.join(map(str, val)) if isinstance(val, list) else str(val)
            L.append(f'{i}. {name}：{v}（按你说的「{src}」整理，对吗？）')
        else:
            blank += 1; opts = f.get('options') or []
            L.append(f'{i}. {name}：____' + (f'（可选：{" / ".join(map(str, opts))}）' if opts else ''))
    L += ['', '都对就回“对”；哪条不对或空着，直接写“序号 + 正确说法”，比如“3 购买后60天内有效”。'
          + ('一时不确定的写“不知道”，我先标【待业务确认】，但它会挡住评审和发布。' if blank else '')]
    print('\n'.join(L))
    print(f'\n（agent：用户答复后，照抄原话写进 brand.yaml 对应字段：{", ".join(f["key"] for _, f in miss)}；预填文件 {pf}）', file=sys.stderr)


def new(a):
    """开下一篇：事实沿用 brand.yaml（不重复问）；参考图可沿用上一篇；首图照片必须换（按稿件存）。"""
    p = C.data_paths(a.data)
    drafts = sorted(x for x in glob.glob(os.path.join(p['drafts'], '*')) if os.path.isdir(x))
    if not drafts: sys.exit('还没有第一篇：先运行 xhs.py quickstart')
    last = os.path.basename(drafts[-1]); m = __import__('re').match(r'^([A-Za-z]*)(\d+)$', last)
    nid = a.new_id or (f'{m.group(1)}{int(m.group(2)) + 1:0{len(m.group(2))}d}' if m else last + '_2')
    d = os.path.join(p['drafts'], nid)
    if os.path.exists(d): sys.exit(f'{nid} 已存在')
    os.makedirs(d)
    lp = pages_of(drafts[-1]); pt = lp.get('post_type') or ''
    open(os.path.join(d, 'copy.md'), 'w', encoding='utf-8').write(f'<!-- 稿件 {nid}：agent 按 steps/04 写完三段后删掉这行里的“待撰写”。待撰写 -->\n# 标题\n\n# 正文\n\n# 标签\n')
    cover = {k: '' for k in ((lp.get('cover') or {}).keys() or ['title', 'subtitle', 'offer', 'cta', 'brand'])}
    if 'brand' in cover: cover['brand'] = '{brand.name}'
    import yaml
    body = {'post_type': pt or '', 'copy_confirmed': '', 'cover_photo': '', 'faces': '', 'reference_feedback': '', 'cover': cover, 'inner': []}
    open(os.path.join(d, 'pages.yaml'), 'w', encoding='utf-8').write(
        f'# 稿件 {nid}：首图照片 cover_photo 和内页照片都按这篇单独放（路径相对本目录），不改全局 layout.yaml\n' + yaml.safe_dump(body, allow_unicode=True, sort_keys=False))
    reused = ''
    src = os.path.join(p['root'], 'refs', last)
    if a.reuse_refs and os.path.isdir(src) and os.listdir(src):
        shutil.copytree(src, os.path.join(p['root'], 'refs', nid)); reused = last
    print(f'已建稿件 {nid}（事实沿用 brand.yaml，已确认的不再问）')
    print('问用户（一条消息，两问都可直接回车用推荐）：')
    print(f'  帖子类型：1. 沿用上一篇：{pt or "上一篇的类型"}（推荐） 2. 换一种（转化帖 / 种草帖）')
    print('  出图方式：' + CHOICE + (f'——选 1 默认沿用 {reused} 的参考图（已复制），也可以发新图' if reused else ''))
    from render_post import needs_photo
    need = needs_photo(layout_of(a.config))
    if need: print(f'  照片：{PHOTO_ASK[need]}——不能沿用上一篇的照片（会撞图）')
    print('主推产品换了才需要重新问价格、包含项、有效期；没换就直接写。')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['status', 'next', 'quickstart', 'card', 'new']); ap.add_argument('--data', default='data')
    ap.add_argument('--config', default='config/brand.yaml'); ap.add_argument('--draft', default='D001')
    ap.add_argument('--no-reference-confirmed', action='store_true', help='quickstart 用：用户看过警告并二次确认不要参考图')
    ap.add_argument('--preset', choices=['极简大标题', '产品主体', '照片满版', '探索地图'], help='quickstart 用：指定出图预设（默认按行业推荐）')
    ap.add_argument('--allow-blank', action='store_true', help='quickstart 用：版式要的照片还没有时也先出纯色底草稿')
    ap.add_argument('--step', type=int, help='card 用：哪一步的确认卡（默认当前步骤）'); ap.add_argument('--prefill', help='card 用：预填文件（默认 <data>/facts_draft.yaml）')
    ap.add_argument('--reuse-refs', action='store_true', help='new 用：沿用上一篇的参考图'); ap.add_argument('--id', dest='new_id', help='new 用：指定新稿件ID')
    a = ap.parse_args()
    if a.cmd == 'quickstart': return quickstart(a)
    if a.cmd == 'card': return card(a)
    if a.cmd == 'new': return new(a)
    n, pending, user_next, act, cmd, *ex = state(a); ex = ex[0] if ex else ''
    if a.cmd == 'status':
        print(f'当前：{tag(n, ex)}'); print(f'待办：{pending}'); print(f'下一步：{user_next}')
    else:
        print(f'做：{tag(n, ex)}，{act}'); print(f'命令：{cmd}'); print(f'读：{STEPFILE[0 if n == "Q" else n]}' + ('（快速起步见“快速通道”一节）' if n == 'Q' else '') + '；回复用户按 docs/交互规范.md')


if __name__ == '__main__':
    main()
