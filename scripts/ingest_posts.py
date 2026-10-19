#!/usr/bin/env python3
"""第 1/2 步 入库：把收件箱里的帖子（手动提供 或 专用小号自动搜集，格式相同）登记进样本库，生成待拆解的空壳行。

收件箱约定（一个帖子一个文件夹，文件夹名随意）：
  data/inbox/bench/<帖子文件夹>/   对标帖
  data/inbox/own/<帖子文件夹>/     自有帖
    01.jpg 02.png …     帖子图片，按文件名排序就是图序（jpg/jpeg/png/webp；截图也行）
    caption.txt         第一行=标题；后面=正文原文；正文里的 #话题 自动提取为标签
    metrics.txt         可选，每行「键: 值」：链接、作者、日期、点赞、收藏、评论、行业、采集方式、采集日期、备注
    comments.txt        可选（对标帖）：每行一条意向评论短证据「评论原文 | 意向判断理由」，不要写用户名
用法
  python scripts/ingest_posts.py --data data            # 入库所有还没入库的文件夹
  python scripts/ingest_posts.py --data data --dry-run  # 只看会入库什么
入库后：图片复制到 data/raw/bench|own/<样本ID>/Pxx.*；文件夹里写 .ingested 记号，重复运行不会重复入库；
同一链接/笔记ID 已在表里的会跳过。观察类字段写成【待拆解】，由 agent 按 templates/拆解模板.md 填写。
"""
import argparse, datetime, glob, hashlib, os, re, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C

IMG = ('.jpg', '.jpeg', '.png', '.webp')
KEYS = {'链接': ['链接', 'url', 'URL', '帖子链接'], '作者': ['作者', '账号', 'author'], '日期': ['日期', '发布日期', 'date'],
        '点赞': ['点赞', '赞', 'likes'], '收藏': ['收藏', '藏', 'saves'], '评论': ['评论', '评', 'comments'], '行业': ['行业'],
        '采集方式': ['采集方式'], '采集日期': ['采集日期'], '备注': ['备注'], '笔记ID': ['笔记ID', 'note_id']}
POST_TODO = {'对标': ['图序观察', '设计结论', '点击机制_推断', '咨询解释', '本品牌迁移', '不可照搬', '查看边界'],
             '自有': ['整体风格', '图组顺序', '顺序判断', '品牌一致性', '建议']}
IMG_TODO = {'对标': ['构图_观察', '主体比例_目测外接框', '字体层级_观察', '配色_观察', '文案卖点_观察', '阅读顺序_推断', '可取之处',
                   '局限', '点击机制_推断', '本品牌迁移建议', '不可照搬', '图示区域_近似归一坐标'],
            '自有': ['构图', '素材', '字体形态', '色彩', '信息层级', '品牌识别', '主要优点', '需要调整', '具体改法']}


def read_kv(path):
    out = {}
    if not os.path.exists(path): return out
    for ln in open(path, encoding='utf-8-sig'):
        m = re.match(r'\s*([^:：]+)\s*[:：]\s*(.*)$', ln)
        if not m: continue
        k, v = m.group(1).strip(), m.group(2).strip()
        for std, al in KEYS.items():
            if k in al: out[std] = v
    return out


def note_id(url):
    m = re.search(r'/(?:explore|discovery/item|item)/([0-9a-zA-Z]{16,})', url or '')
    return m.group(1) if m else ''


def date_status(d):
    d = (d or '').strip()
    if not d: return '待核'
    if '编辑于' in d: return '编辑时间，首次发布日期未知'
    if re.search(r'(19|20)\d\d[-/.年]\d{1,2}[-/.月]\d{1,2}', d): return '帖内显示完整日期'
    return '页面显示原样，年份/首次发布日期待核'


def browser_allowed(cfg_path):
    """模式 B（专用小号自动）采集的帖子：brand.yaml 必须确认 browser 模式、不是主运营号、用户接受平台风险。"""
    if not cfg_path or not os.path.exists(cfg_path): return '没有提供 --config，无法核对模式 B 的前置确认'
    cfg = C.load_yaml(cfg_path); col = cfg.get('collection') or {}
    bad = [m for ok, m in ((col.get('mode') == 'browser', 'collection.mode 不是 browser'), (col.get('is_main_account') is False, 'is_main_account 不是 false'),
                           (col.get('user_accepts_platform_risk') is True, '用户还没确认接受平台风险（user_accepts_platform_risk）')) if not ok]
    return '；'.join(bad)


def next_id(rows, prefix, width):
    nums = [int(m.group(1)) for r in rows for m in [re.match(prefix + r'-(\d+)$', r.get('样本ID', ''))] if m]
    return f'{prefix}-{(max(nums) + 1 if nums else 1):0{width}d}'


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--data', default='data'); ap.add_argument('--inbox', help='默认 <data>/inbox'); ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--config', help='brand.yaml；收件箱里有「采集方式: 专用小号自动」的帖子时必须提供，用来核对模式 B 的前置确认')
    a = ap.parse_args(); p = C.data_paths(a.data); inbox = a.inbox or os.path.join(p['root'], 'inbox')
    posts = C.load_table(p, '爆款样本库_样本帖子'); imgs = C.load_table(p, '爆款样本库_样本图片'); ev = C.load_table(p, '对标咨询证据')
    seen = {r.get('帖子链接') for r in posts if r.get('帖子链接')} | {r.get('笔记ID') for r in posts if r.get('笔记ID')}
    today = datetime.date.today().isoformat(); done = []; skipped = []
    for kind, sub in (('对标', 'bench'), ('自有', 'own')):
        for d in sorted(glob.glob(os.path.join(inbox, sub, '*'))):
            if not os.path.isdir(d) or os.path.exists(os.path.join(d, '.ingested')): continue
            files = sorted(f for f in os.listdir(d) if f.lower().endswith(IMG))
            cap = open(os.path.join(d, 'caption.txt'), encoding='utf-8-sig').read().strip() if os.path.exists(os.path.join(d, 'caption.txt')) else ''
            if not files and not cap:
                skipped.append(f'{d}：没有图片也没有 caption.txt'); continue
            kv = read_kv(os.path.join(d, 'metrics.txt')); url = kv.get('链接', ''); nid = kv.get('笔记ID') or note_id(url)
            if '专用小号' in kv.get('采集方式', '') or '自动' in kv.get('采集方式', ''):
                why = browser_allowed(a.config)
                if why: skipped.append(f'{d}：模式 B 采集的帖子，但 {why} → 拒绝入库（见 steps/01 模式 B 的三条前置确认）'); continue
            if (url and url in seen) or (nid and nid in seen):
                skipped.append(f'{d}：链接/笔记ID 已在样本库里'); continue
            lines = cap.splitlines(); title = lines[0].strip() if lines else C.TODO
            body = '\n'.join(lines[1:]).strip(); tags = ' '.join(dict.fromkeys(re.findall(r'#[^\s#]+', cap)))
            sid = next_id(posts, 'BM', 3) if kind == '对标' else next_id(posts, 'OWN', 2)
            src_type = '对标' if kind == '对标' else '自有·' + (kv.get('备注') or '待补账号用途')
            inter = '；'.join(f'{k} {kv[k]}' for k in ('点赞', '收藏', '评论') if kv.get(k))
            row = {'样本ID': sid, '来源类型': src_type, '账号或作者': kv.get('作者', ''), '标题': title, '行业': kv.get('行业', ''),
                   '笔记ID': nid, '帖子链接': url, '发布日期原样': kv.get('日期', ''),
                   '日期证据状态': date_status(kv.get('日期', '')),
                   '图片数': len(files), '已取全图': '待核', '正文原文': body, '标签': tags,
                   '文案记录方式': '标题与正文按页面原样记录' if body else ('原帖正文只有话题标签' if tags else '只有标题'),
                   '互动与日期': (f'采集时公开底栏：{inter}。无数字标签不补零；没有曝光/私信/到店/成交，不做转化或设计因果推断。' if inter else '采集时未记录互动数字（不补零）') + (f'；页面显示：{kv["日期"]}' if kv.get('日期') else ''),
                   '版权状态': '仅研究，不商用' if kind == '对标' else '自有', '采集方式': kv.get('采集方式', '手动提供'),
                   '采集日期': kv.get('采集日期', today), '来源文件': os.path.relpath(d, p['root']), '待核事项': ''}
            if kind == '对标':
                row.update(筛选状态='待核：门槛（近一年+不同用户意向评论数）未核', 正式合格='候选', 评论核验口径=C.TODO)
            for k in POST_TODO[kind]: row[k] = C.TODO
            dst = os.path.join(p['raw'], sub, sid)
            if not a.dry_run: os.makedirs(dst, exist_ok=True)
            for i, f in enumerate(files, 1):
                src = os.path.join(d, f); ext = os.path.splitext(f)[1].lower(); out = os.path.join(dst, f'P{i:02d}{ext}')
                w = h = ''
                try:
                    from PIL import Image
                    with Image.open(src) as im: w, h = im.size
                except Exception: pass
                ir = {'图片ID': f'{sid}_P{i:02d}', '样本ID': sid, '来源类型': src_type, '图序': i, '图片角色': '首图' if i == 1 else C.TODO,
                      '帖子链接': url, '原图相对路径': os.path.relpath(out, p['root']), '图片SHA256': hashlib.sha256(open(src, 'rb').read()).hexdigest(),
                      '宽px': w, '高px': h, '原图类型': '截图/手动提供' if row['采集方式'].startswith('手动') else '网页配图（专用小号采集）',
                      '已看实图': '否', '含AI内容': '待核', '版权状态': row['版权状态']}
                for k in IMG_TODO[kind]: ir[k] = C.TODO
                imgs.append(ir)
                if not a.dry_run: shutil.copy2(src, out)
            cp = os.path.join(d, 'comments.txt')
            if kind == '对标' and os.path.exists(cp):
                n0 = len(ev)
                for ln in open(cp, encoding='utf-8-sig'):
                    if not ln.strip(): continue
                    c, _, why = ln.partition('|')
                    ev.append({'匿名编号': f'C{len(ev) + 1:03d}', '样本ID': sid, '资格': '候选', '所属帖子': title,
                               '评论短证据': c.strip()[:60], '原有意向判断理由': why.strip() or C.TODO, '原帖链接': url})
                row['已核意向评论下限'] = len(ev) - n0
            posts.append(row); seen |= {url, nid} - {''}
            if not a.dry_run: open(os.path.join(d, '.ingested'), 'w').write(sid + '\n')
            done.append(f'{sid} ← {os.path.relpath(d, inbox)}（{len(files)} 图，标题：{title[:30]}）')
    if not a.dry_run and done:
        C.save_table(p, '爆款样本库_样本帖子', posts); C.save_table(p, '爆款样本库_样本图片', imgs); C.save_table(p, '对标咨询证据', ev)
    print(('【预演】' if a.dry_run else '') + f'入库 {len(done)} 篇：'); [print('  +', x) for x in done]
    for s in skipped: print('  跳过', s)
    if done: print(f'下一步：agent 打开每张原图，按 templates/拆解模板.md 把【待拆解】逐项填完，再运行 build_tables.py。')


if __name__ == '__main__':
    main()
