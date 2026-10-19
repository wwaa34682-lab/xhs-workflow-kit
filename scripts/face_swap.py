#!/usr/bin/env python3
"""可选：照片人脸处理（第 5 步）。按 brand.yaml 的 face_policy 处理“不能用原脸”的人。

模式
  blur     高斯模糊人脸（只要 opencv-python-headless；不算 AI 内容）
  sticker  用圆形色块/emoji 贴纸挡脸（只要 opencv；不算 AI 内容；注意风格锁 SL-G06：主视觉别用贴纸挡脸照）
  swap     AI 换脸：把脸换成“合成的非真实人物”（需要 insightface + onnxruntime + 你自己下载的模型文件）
           ⚠ 发布时必须在小红书勾选「含AI生成内容」；禁止换成真实存在的人/公众人物的脸。
           ⚠ 许可：insightface 的 inswapper_128 等预训练模型官方声明仅限非商业研究用途；商业账号使用前，
             请自行确认模型许可或改用有商用授权的换脸服务。本工具包不分发任何模型。
用法
  python scripts/face_swap.py --check                                     # 检查依赖
  python scripts/face_swap.py --mode blur --in a.jpg --out a_blur.jpg [--keep 0]   # --keep 指定保留原脸的人（按从左到右序号，如员工本人）
  python scripts/face_swap.py --mode sticker --in a.jpg --out b.jpg --color "#F06A4E"
  python scripts/face_swap.py --mode swap --in a.jpg --out c.jpg --source synthetic_face.jpg --models ~/.insightface/models
  python scripts/face_swap.py ... --boxes "x,y,w,h;x,y,w,h"              # 自动检测不到时手动给人脸框
  加 --data data --draft D001 会把发布队列该稿件的「含AI内容」标成“是”（仅 swap 模式），并写入待确认事项提醒。
"""
import argparse, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C


def need_cv2():
    try:
        import cv2; return cv2
    except ImportError:
        sys.exit('需要 opencv：pip install opencv-python-headless')


def detect(cv2, img, boxes):
    if boxes:
        return [tuple(int(v) for v in b.split(',')) for b in boxes.split(';') if b.strip()]
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    cas = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    f = cas.detectMultiScale(g, 1.1, 5, minSize=(40, 40))
    return sorted([tuple(map(int, b)) for b in f], key=lambda b: b[0])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--check', action='store_true'); ap.add_argument('--mode', choices=['blur', 'sticker', 'swap'])
    ap.add_argument('--in', dest='inp'); ap.add_argument('--out'); ap.add_argument('--keep', default='', help='保留原脸的序号（从左到右，0 开始），逗号分隔')
    ap.add_argument('--boxes'); ap.add_argument('--color', default='#FFFFFF'); ap.add_argument('--source', help='合成人脸图（非真实人物）')
    ap.add_argument('--models', default='~/.insightface/models'); ap.add_argument('--data'); ap.add_argument('--draft')
    a = ap.parse_args()
    if a.check:
        for m in ('cv2', 'insightface', 'onnxruntime'):
            try: __import__(m); print('✓', m)
            except ImportError: print('✗', m, '（blur/sticker 只需要 cv2；swap 三个都要）')
        mp = os.path.expanduser(a.models); print('模型目录', mp, '存在' if os.path.isdir(mp) else '不存在（swap 需要 inswapper_128.onnx 和 buffalo_l）')
        return
    if not (a.mode and a.inp and a.out): ap.error('需要 --mode --in --out')
    cv2 = need_cv2(); import numpy as np
    img = cv2.imread(a.inp); keep = {int(k) for k in a.keep.split(',') if k.strip().isdigit()}
    if a.mode in ('blur', 'sticker'):
        faces = detect(cv2, img, a.boxes)
        for i, (x, y, w, h) in enumerate(faces):
            if i in keep: continue
            if a.mode == 'blur':
                pad = int(.15 * w); x0, y0 = max(0, x - pad), max(0, y - pad); roi = img[y0:y + h + pad, x0:x + w + pad]
                img[y0:y + h + pad, x0:x + w + pad] = cv2.GaussianBlur(roi, (0, 0), max(8, w / 6))
            else:
                r, g, b = C.hex2rgb(a.color, (255, 255, 255))
                cv2.circle(img, (x + w // 2, y + h // 2), int(max(w, h) * .62), (b, g, r), -1, cv2.LINE_AA)
        print(f'{a.mode}：检测到 {len(faces)} 张脸，处理 {len([i for i in range(len(faces)) if i not in keep])} 张')
    else:
        try:
            import insightface
            from insightface.app import FaceAnalysis
        except ImportError:
            sys.exit('swap 模式需要：pip install insightface onnxruntime（以及模型文件，见顶部许可说明）')
        if not a.source: sys.exit('swap 需要 --source：一张合成的非真实人物人脸图')
        md = os.path.expanduser(a.models)
        app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider']); app.prepare(ctx_id=-1, det_size=(640, 640))
        sw = insightface.model_zoo.get_model(os.path.join(md, 'inswapper_128.onnx'), providers=['CPUExecutionProvider'])
        si = cv2.imread(a.source); found = app.get(si)
        if not found:  # 紧裁的人脸图要加边框才检测得到
            si = cv2.copyMakeBorder(cv2.resize(si, (512, 512)), 256, 256, 256, 256, cv2.BORDER_CONSTANT, value=(128, 128, 128)); found = app.get(si)
        if not found: sys.exit('合成人脸图里检测不到人脸，换一张正脸、清晰的图')
        src = max(found, key=lambda f: f.det_score)
        faces = sorted(app.get(img), key=lambda f: f.bbox[0]); n = 0
        for i, f in enumerate(faces):
            if i not in keep: img = sw.get(img, f, src, paste_back=True); n += 1
        print(f'swap：检测到 {len(faces)} 张脸，换了 {n} 张（合成身份）')
        if n == 0: print('没有换任何脸：检测不到时用更大的原图，或改用 blur/sticker + --boxes')
        else: print('⚠ 这张图含 AI 生成内容：发布时必须勾选「含AI生成内容」')
        if n and a.data and a.draft:
            p = C.data_paths(a.data); q = C.load_table(p, '发布队列')
            for r in q:
                if r.get('稿件ID') == a.draft:
                    r['含AI内容'] = '是'
                    if '含AI' not in r.get('待确认事项', ''):
                        r['待确认事项'] = '；'.join(x for x in [r.get('待确认事项', ''), '发布时勾选「含AI生成内容」'] if x)
            C.save_table(p, '发布队列', q); print('发布队列已标注 含AI内容=是')
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True); cv2.imwrite(a.out, img); print('输出', a.out)


if __name__ == '__main__':
    main()
