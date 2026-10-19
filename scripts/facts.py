"""必问事实清单（config/required_facts.yaml）的检查：xhs.py、ledger.py 共用。业务事实不允许默认值。"""
import os
import common as C

REQ = os.path.join(C.KIT, 'config', 'required_facts.yaml')


def load():
    return C.load_yaml(REQ)


def _val_ok(v, check):
    if check == 'bool': return isinstance(v, bool)
    if check == 'true': return v is True
    if check == 'false': return v is False
    if check == 'list':
        return isinstance(v, list) and len(v) > 0 and not any(C.is_unknown(x) for x in v)
    if isinstance(v, (list, dict)): return len(v) > 0 and C.UNKNOWN not in str(v)
    return not C.is_unknown(v)


def _when_ok(cfg, cond):
    if not cond: return True
    k, want = [s.strip() for s in cond.split('==')]
    v = C.get(cfg, k)
    return str(v).lower() == want.lower()


def missing(cfg, steps):
    """返回 steps（步骤号列表）里缺的事实：[(步骤号, fact dict), ...]"""
    req = load(); out = []
    try: extra = C.load_profile(cfg).get('extra_required') or []   # 合规包加的题：默认第 4 步问，写了 step 的按 step
    except SystemExit: extra = []
    for n in steps:
        for f in (req['steps'].get(n) or {}).get('facts', []) + [x for x in extra if int(x.get('step', 4)) == n]:
            if _when_ok(cfg, f.get('when')) and not _val_ok(C.get(cfg, f['key']), f.get('check', 'filled')):
                out.append((n, f))
    return out


def gate(cfg, name):
    return missing(cfg, load()['gates'][name])


def label(f):
    """给用户看的白话名字（不露字段名）：优先 label，否则取问题里第一个问号之前的部分。"""
    if f.get('label'): return f['label']
    a = str(f.get('ask', f['key'])); a = a.split('）', 1)[-1] if a.startswith('（') else a
    return a.split('？')[0].split('?')[0].strip() or f['key']


def irrelevant(cfg, key):
    """这一项在当前情况下不用问（例如没开聚光时的 juguang.*）：build_tables / 收尾提示不把它算作待确认。"""
    if str(key).startswith('juguang.') and key != 'juguang.has' and C.get(cfg, 'juguang.has') is False: return True
    req = load()
    for st in req['steps'].values():
        for f in (st or {}).get('facts', []):
            if f['key'] == key and f.get('when') and not _when_ok(cfg, f['when']): return True
    return False


def ask_line(f):
    opts = f.get('options') or []
    o = ' '.join(f'{i}. {x}' for i, x in enumerate(opts, 1))
    return f'{f["ask"]}' + (f'（{o}）' if o else '')


def report(miss):
    return '；'.join(f'第{n}步 {f["key"]}' for n, f in miss)
