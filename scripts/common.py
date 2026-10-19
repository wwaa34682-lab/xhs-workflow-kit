"""公共工具：读配置、读写表、字体查找、数字解析。所有脚本都只依赖本文件 + 标准库 + requirements.txt。"""
import csv, os, re, sys, glob, json

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL = os.path.join(KIT, 'templates')
UNKNOWN = '【待业务确认】'
SIM_LABEL = '【模拟演练，非真实数据】'
TODO = '【待拆解】'

TABLES = ['爆款样本库_样本帖子', '爆款样本库_样本图片', '对标咨询证据', '自有账号摘要', '风格锁', '评审回流库', '发布队列', '投放效果库', '投放映射', '自然流量库']


def load_profile(cfg):
    """按 brand.yaml 的 compliance.profile 加载 config/compliance/<名>.yaml；没写就用“通用”。"""
    name = str((cfg.get('compliance') or {}).get('profile') or '通用')
    if is_unknown(name): name = '通用'
    path = os.path.join(KIT, 'config', 'compliance', name + '.yaml')
    if not os.path.exists(path):
        sys.exit(f'找不到合规起步包 {path}；可选：' + '、'.join(os.path.splitext(f)[0] for f in os.listdir(os.path.dirname(path)) if f.endswith('.yaml')))
    prof = load_yaml(path); prof['_id'] = name
    return prof


def load_yaml(path):
    try:
        import yaml
    except ImportError:
        sys.exit('缺少 PyYAML：pip install -r requirements.txt')
    with open(path, encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def data_paths(data):
    data = os.path.abspath(os.path.expanduser(data))
    p = dict(root=data, tables=os.path.join(data, 'tables'), exports=os.path.join(data, 'exports'),
             drafts=os.path.join(data, 'drafts'), out=os.path.join(data, 'out'), raw=os.path.join(data, 'raw'),
             sim=os.path.join(data, 'sim'))
    return p


def schema(name):
    with open(os.path.join(TPL, 'tables', name + '.csv'), encoding='utf-8-sig') as f:
        return next(csv.reader(f))


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, cols):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction='ignore')
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, '') for c in cols})


def table_path(paths, name):
    return os.path.join(paths['tables'], name + '.csv')


def load_table(paths, name):
    return read_csv(table_path(paths, name))


def save_table(paths, name, rows):
    write_csv(table_path(paths, name), rows, schema(name))


def num(v):
    v = str(v if v is not None else '').replace(',', '').replace('%', '').replace('¥', '').strip()
    try:
        return float(v)
    except ValueError:
        return 0.0


def pick(row, keys, default=''):
    for k in keys:
        if k in row and str(row[k]).strip() not in ('', '-'):
            return row[k]
    return default


def pct(x):
    return '—' if x is None else f'{x * 100:.2f}%'


def money(x):
    return '—' if x is None else f'{x:,.2f}'


def hex2rgb(h, default=(0, 0, 0)):
    if isinstance(h, (list, tuple)):
        return tuple(int(v) for v in h[:3])
    h = str(h or '').strip().lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    if not re.fullmatch(r'[0-9a-fA-F]{6}', h):
        return default
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def get(cfg, dotted, default=None):
    cur = cfg
    for k in dotted.split('.'):
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        elif isinstance(cur, list) and k.isdigit() and int(k) < len(cur):
            cur = cur[int(k)]
        else:
            return default
    return cur


def is_unknown(v):
    return v is None or str(v).strip() == '' or UNKNOWN in str(v)


# ---------------------------------------------------------------- fonts
SYSTEM_CJK = [
    '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc', '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc',
    '/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc', '/System/Library/Fonts/PingFang.ttc',
    '/System/Library/Fonts/STHeiti Medium.ttc', 'C:/Windows/Fonts/msyh.ttc', 'C:/Windows/Fonts/simhei.ttf',
]
_warned = set()


def font_path(cfg, role):
    """role = title / body / number。先找 brand.yaml fonts.<role>.file，再找 fonts/ 目录，最后回退系统中文字体。"""
    spec = get(cfg, f'brand.fonts.{role}', {}) or {}
    fname = spec.get('file') if isinstance(spec, dict) else spec
    dirs = [get(cfg, 'brand.fonts.dir'), os.path.join(KIT, 'fonts'), os.path.expanduser('~/fonts')]
    if fname:
        if os.path.isabs(os.path.expanduser(fname)) and os.path.exists(os.path.expanduser(fname)):
            return os.path.expanduser(fname)
        for d in dirs:
            if not d:
                continue
            hits = glob.glob(os.path.join(os.path.expanduser(d), '**', fname), recursive=True)
            if hits:
                return hits[0]
    for p in SYSTEM_CJK + glob.glob('/usr/share/fonts/**/*CJK*.tt*', recursive=True):
        if os.path.exists(p):
            if role not in _warned:
                _warned.add(role)
                print(f'[字体] 没找到 {role} 字体「{fname}」，暂用系统字体 {os.path.basename(p)}。'
                      f'运行 python scripts/fetch_fonts.py 下载免费商用字体。', file=sys.stderr)
            return p
    sys.exit('找不到任何中文字体：请运行 python scripts/fetch_fonts.py，或在 brand.yaml 的 fonts.dir 指向字体目录')


def font(cfg, role, size):
    from PIL import ImageFont
    return ImageFont.truetype(font_path(cfg, role), int(size))


def dump_json(obj, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, default=str)


def wrap_text(draw, s, f, width):
    out, cur = [], ''
    for ch in str(s):
        if ch == '\n':
            out.append(cur); cur = ''; continue
        if draw.textlength(cur + ch, font=f) > width and cur:
            out.append(cur); cur = ch
        else:
            cur += ch
    return out + ([cur] if cur else [])
