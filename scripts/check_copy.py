#!/usr/bin/env python3
"""第 4 步 文案事实与合规校验：正文里的价格、数量、规格、门店、优惠、资质、承诺用语，都必须能在 brand.yaml 找到出处，
并按行业合规起步包（brand.yaml 的 compliance.profile → config/compliance/<名>.yaml）检查违禁词、违禁句式和必带免责语。

用法  python scripts/check_copy.py --config config/brand.yaml --copy data/drafts/D001/copy.md [--pages data/drafts/D001/pages.yaml]
退出码 0=通过；1=有必须改的问题（编造嫌疑、违禁词或句式、缺免责语、缺情景演绎标注、资质无出处、还有【待业务确认】）。
"""
import argparse, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C

# 数字 + 单位/量词：价格、时长、份量、规格、数量。没有出处 → 必须改；数字有但单位不同 → 提示
UNITS = ('元|块|折|分钟|小时|节|次|天|周|个月|月|年|人|位|家|%|％|cm|厘米|mm|毫米|kg|千克|公斤|斤|g|克|ml|mL|毫升|L|升|'
         '杯|个|颗|颗牙|张|份|件|瓶|支|盒|袋|罐|碗|盘|道|款|种|平米|㎡|平方米|层|座|桌|间|岁|期|课时|堂|步|分')
NUM_RE = re.compile(r'\d+(?:\.\d+)?\s*(?:' + UNITS + r')(?![a-zA-Z])')
# 不带数字的优惠和承诺：brand.yaml 里没有出处时必须改
OFFER_WORDS = ['半价', '买一送一', '买一赠一', '第二杯', '第二份', '免费', '免单', '赠送', '送', '包邮', '限时', '首单', '首次', '新客',
               '特价', '秒杀', '打折', '折扣', '满减', '优惠券', '会员价', '团购', '套餐价', '不限次', '无限次', '终身']
# 紧迫感/稀缺说法（风格锁 SL-G03）：业务没确认过（brand.yaml 里找不到）就必须改
URGENCY_WORDS = ['名额有限', '仅剩', '最后几个名额', '限量', '售完即止', '即将涨价', '马上涨价', '报名从速', '立即报名', '手慢无', '错过再等', '倒计时']
# 服务承诺：不带数字也算事实，必须在 offer / allowed_claims 里有出处
PROMISE_WORDS = ['不办卡', '不推销', '零推销', '不强制消费', '不强制', '无隐形消费', '无隐形收费', '没有隐形消费', '无套路', '不满意退', '随时退',
                 '无条件退', '包退', '包教包会', '学不会退', '不加价', '不收押金', '全程一对一', '一对一']
ORDINAL_OK = re.compile(r'第[一二三四五六七八九十\d]+(?:步|次|节|课|天|口|杯|眼|站|篇|页|张|组|轮|个)')


def flatten(o):
    if isinstance(o, dict): return ' '.join(flatten(v) for v in o.values())
    if isinstance(o, list): return ' '.join(flatten(v) for v in o)
    return '' if C.is_unknown(o) else str(o)


PAGE_META = {'post_type', 'copy_confirmed', 'cover_photo', 'cover_subject', 'faces', 'reference_feedback', 'variants', 'reference_from'}
PAGE_SKIP = {'photo', 'photos', 'frame', 'photo_label'}


def pages_text(path):
    """只取会印在图上的文字（cover 各槽位、inner 的标题和说明）；稿件的记录字段（faces、copy_confirmed…）和照片路径不参与检查。"""
    pg = C.load_yaml(path) or {}; out = []
    def walk(o):
        if isinstance(o, dict): [walk(v) for k, v in o.items() if k not in PAGE_SKIP]
        elif isinstance(o, list): [walk(v) for v in o]
        elif o is not None: out.append(str(o))
    for k, v in pg.items():
        if k not in PAGE_META: walk(v)
    return '\n'.join(out)


def strip_allowed(text, allow):
    for w in sorted(allow or [], key=len, reverse=True):
        text = text.replace(w, '□' * len(w))
    return text


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--config', default='config/brand.yaml'); ap.add_argument('--copy', required=True); ap.add_argument('--pages')
    ap.add_argument('--story', choices=['auto', 'real', 'scenario'], default='auto', help='第一人称故事是真实经历(real)还是情景演绎(scenario)')
    a = ap.parse_args(); cfg = C.load_yaml(a.config); prof = C.load_profile(cfg)
    text = open(a.copy, encoding='utf-8').read()
    text = re.sub(r'<!--.*?-->', '', text, flags=re.S)
    if a.pages: text += '\n' + pages_text(a.pages)
    body = re.sub(r'#\S+', ' ', text)            # 话题标签不参与事实/门店检查
    rules_cfg = dict(cfg); rules_cfg.pop('content_rules', None)
    facts = flatten(rules_cfg) + ' ' + flatten((cfg.get('content_rules') or {}).get('allowed_claims') or [])
    facts_n = re.sub(r'\s', '', facts)
    errs, warns = [], []
    # 1) 数字 + 单位
    for m in sorted(set(NUM_RE.findall(body))):
        core = re.sub(r'\s', '', m); num = re.match(r'\d+(?:\.\d+)?', core).group()
        if core in facts_n: continue
        if core.endswith('家') and int(float(num)) == len(cfg.get('locations') or []): continue
        if num in facts_n: warns.append(f'「{m}」：数字在 brand.yaml 里有，但单位/口径不同，请核对'); continue
        errs.append(f'「{m}」：brand.yaml 里找不到这个事实 → 改成已确认口径，或写【待业务确认】')
    for m in sorted(set(re.findall(r'(?<![\d.])\d{2,}(?![\d.]|\s*(?:' + UNITS + r'))', body))):
        if m not in facts_n and not re.fullmatch(r'20\d\d', m): warns.append(f'「{m}」：没找到出处的数字，确认是不是事实')
    # 2) 不带数字的优惠/承诺
    for w in OFFER_WORDS:
        if w in body and w not in facts:
            ctx = re.search(r'.{0,6}' + re.escape(w) + r'.{0,6}', body).group().strip()
            if w in ('送', '首次', '新客') and not re.search(r'(?:送|赠)[^\s，。]{1,6}|首次.{0,3}(?:价|优惠|立减)|新客.{0,3}(?:价|优惠|专享|立减)', ctx):
                continue
            errs.append(f'优惠/承诺「{w}」（…{ctx}…）：brand.yaml 的 offer 里没有 → 业务确认后写进 offer.notes 或 includes')
    for w in URGENCY_WORDS:
        if w in body and w not in facts:
            errs.append(f'紧迫感说法「{w}」（风格锁 SL-G03）：业务没确认过 → 删掉；确实属实，请业务确认后写进 offer.notes')
    for w in PROMISE_WORDS:
        if w in body and w not in facts and not (w == '一对一' and '全程一对一' in body and '全程一对一' in facts):
            errs.append(f'服务承诺「{w}」：brand.yaml 的 offer / allowed_claims 里没有 → 删掉，或请业务确认后写进 offer.notes / allowed_claims')
    for t in prof.get('fact_terms') or []:   # 合规包里“必须在 offer 里有出处”的说法（如教育的“外教”）
        if t in body and t not in facts:
            errs.append(f'「{t}」（{prof["_id"]}起步包）：brand.yaml 的 offer / qualifications 里没有 → 删掉，或请业务确认后写进 offer')
    # 3) 门店（跳过 #标签）
    names = [str(l.get('name') if isinstance(l, dict) else l) for l in cfg.get('locations') or []]
    for m in set(re.findall(r'[\u4e00-\u9fa5]{1,6}(?:店|馆|中心|工作室)', body)):
        if any(m in n or n in m for n in names) or m in facts: continue
        if re.search(r'(门店|本店|全店|到店|进店|开店|探店|小店|这家店|咖啡馆|餐馆|饭馆|体验馆|分店|总店|各店|每家店|家店|的店|附近店)$', m): continue
        warns.append(f'「{m}」看起来像门店名，但不在 brand.yaml locations 里')
    # 4) 违禁词（白名单 + 序数词放行）+ 违禁句式
    scan = strip_allowed(ORDINAL_OK.sub(lambda x: '□' * len(x.group()), body), prof.get('allow'))
    for w in dict.fromkeys((C.get(cfg, 'content_rules.banned_words', []) or []) + (prof.get('banned') or [])):
        if not w: continue
        if str(w).startswith('re:'):
            if re.search(str(w)[3:], scan): errs.append(f'违禁句式：「{re.search(str(w)[3:], scan).group()}」')
        elif str(w) in scan: errs.append(f'违禁/绝对化用语：「{w}」')
    for pat in prof.get('banned_patterns') or []:
        for hit in sorted(set(x.group() for x in re.finditer(pat, scan))):
            errs.append(f'违禁句式（{prof["_id"]}起步包）：「{hit}」')
    # 5) 资质类说法必须有出处
    quals = flatten(cfg.get('qualifications') or [])
    for t in prof.get('qualification_terms') or []:
        if t in body and t not in quals:
            errs.append(f'资质说法「{t}」：brand.yaml 的 qualifications 里没有原文 → 删掉，或请业务提供资质原文后写进 qualifications')
    # 6) 必带免责语
    for d in prof.get('required_disclaimers') or []:
        if d not in text: errs.append(f'缺少免责语「{d}」（{prof["_id"]}起步包要求）')
    # 7) 待确认
    n = text.count(C.UNKNOWN)
    if n: errs.append(f'还有 {n} 处{C.UNKNOWN}：业务确认后才能发布')
    # 8) 第一人称故事：通用行业要标“情景演绎”；受监管行业（story_rule: off）一律不允许
    label = C.get(cfg, 'content_rules.scenario_label', '*本文为情景演绎')
    # 机构口吻“我们…”不算第一人称体验故事；只认“我”（不含“我们”）和体验/家长句式
    first_person = len(re.findall(r'我(?!们)', body)) >= 2 or re.search(r'(才发现|真去试|第一次去|我家(?:孩子|娃|宝|小朋友|女儿|儿子)|我(?:去|试了|觉得|发现)(?!们))', body)
    if prof.get('story_rule') in ('off', False):   # YAML 里不加引号的 off 会被读成 False
        if first_person or a.story == 'scenario':
            errs.append(f'{prof["_id"]}行业不能用第一人称体验故事或顾客/患者口吻（“情景演绎”标注也不行）→ 改成机构或专业人员的科普口吻')
    elif a.story == 'scenario' or (a.story == 'auto' and first_person):
        if label.strip('*') not in text:
            (errs if a.story == 'scenario' else warns).append(f'有第一人称/体验故事但没写「{label}」；如果是真实用户经历，用 --story real 并确认有授权')
    # 9) CTA 关键词
    kw = C.get(cfg, 'content_rules.comment_keyword')
    if kw and not C.is_unknown(kw) and kw not in text: warns.append(f'没看到评论关键词「{kw}」（风格锁 SL-G11）')
    print(f'检查 {os.path.basename(a.copy)}（合规包：{prof["_id"]}）：{len(errs)} 个必须改，{len(warns)} 个提示')
    for e in dict.fromkeys(errs): print('  ✗', e)
    for w in dict.fromkeys(warns): print('  ·', w)
    sys.exit(1 if errs else 0)


if __name__ == '__main__':
    main()
