#!/usr/bin/env python3
"""拆解填表助手：按“字段名”填，不用手改几十列宽的 CSV。

  # 1) 给某个样本生成填空模板（只列还是【待拆解】的字段，帖子 + 它的每张图）
  python scripts/fill_breakdown.py --data data template BM-004            > data/breakdown/BM-004.yaml
  # 2) agent 填好 YAML 后写回（校验列名，未知列直接拒绝；没改的字段保持原样）
  python scripts/fill_breakdown.py --data data apply data/breakdown/BM-004.yaml
  # 3) 单个字段快速改
  python scripts/fill_breakdown.py --data data set BM-004 设计结论="……" 图序观察="……"
YAML 格式：顶层键是 样本ID（写入 爆款样本库_样本帖子）或 图片ID（形如 BM-004_P01，写入 爆款样本库_样本图片），值是 {字段名: 内容}。
字段名和含义见 templates/拆解模板.md；对标帖填 A 部分字段，自有帖填 B 部分字段。
"""
import argparse, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C

POST, IMG = '爆款样本库_样本帖子', '爆款样本库_样本图片'


def table_for(key):
    return (IMG, '图片ID') if '_P' in key else (POST, '样本ID')


def apply_updates(p, updates):
    by_table = {}
    for key, fields in updates.items():
        t, idc = table_for(str(key)); by_table.setdefault(t, []).append((str(key), idc, fields or {}))
    total = 0
    for t, items in by_table.items():
        rows = C.load_table(p, t); cols = C.schema(t); idx = {r[items[0][1]]: r for r in rows}
        for key, idc, fields in items:
            bad = [k for k in fields if k not in cols]
            if bad: sys.exit(f'✗ {key}：表「{t}」没有这些列：{"、".join(bad)}（列名见 templates/拆解模板.md）')
            if key not in idx: sys.exit(f'✗ 找不到 {key}：先用 ingest_posts.py 入库')
            for k, v in fields.items():
                if k == idc: continue
                idx[key][k] = '' if v is None else str(v).strip(); total += 1
        C.save_table(p, t, rows)
    keys = set(updates); sids = {k.split('_P')[0] for k in keys}
    left = sum(1 for r in C.load_table(p, POST) if r['样本ID'] in sids for v in r.values() if v == C.TODO) + \
        sum(1 for r in C.load_table(p, IMG) if r.get('样本ID') in sids for v in r.values() if v == C.TODO)
    print(f'已写入 {total} 个字段；这些样本还剩 {left} 格{C.TODO}')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--data', default='data'); sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('template'); s.add_argument('sid'); s.add_argument('--all', action='store_true', help='列出全部字段（默认只列【待拆解】的）')
    s = sub.add_parser('apply'); s.add_argument('file')
    s = sub.add_parser('set'); s.add_argument('key'); s.add_argument('pairs', nargs='+', help='字段=内容')
    a = ap.parse_args(); p = C.data_paths(a.data)
    if a.cmd == 'template':
        import yaml
        out = {}
        for r in C.load_table(p, POST):
            if r['样本ID'] == a.sid: out[a.sid] = {k: v for k, v in r.items() if a.all or v == C.TODO}
        for r in C.load_table(p, IMG):
            if r.get('样本ID') == a.sid: out[r['图片ID']] = {k: v for k, v in r.items() if a.all or v == C.TODO}
        if not out: sys.exit(f'找不到 {a.sid}')
        print(f'# {a.sid} 的拆解填空模板：把【待拆解】换成内容（按 templates/拆解模板.md），然后 fill_breakdown.py apply 本文件')
        print(yaml.safe_dump(out, allow_unicode=True, sort_keys=False, width=1000))
    elif a.cmd == 'apply':
        apply_updates(p, C.load_yaml(a.file))
    else:
        kv = {}
        for pr in a.pairs:
            if '=' not in pr: sys.exit(f'格式是 字段=内容：{pr}')
            k, v = pr.split('=', 1); kv[k.strip()] = v
        apply_updates(p, {a.key: kv})


if __name__ == '__main__':
    main()
