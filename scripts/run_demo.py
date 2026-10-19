#!/usr/bin/env python3
"""一键跑通虚构 demo（10 步里能自动化的部分）：python scripts/run_demo.py [--to demo_run] [--fast]
会把 examples/demo/ 复制到 demo_run/ 再运行，examples/ 本身不被修改。全部数据都是虚构的。"""
import argparse, os, shutil, subprocess, sys
KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ap = argparse.ArgumentParser(); ap.add_argument('--to', default=os.path.join(KIT, 'demo_run')); ap.add_argument('--fast', action='store_true', help='只出首图')
a = ap.parse_args(); D = os.path.abspath(a.to)
if os.path.exists(D): shutil.rmtree(D)
shutil.copytree(os.path.join(KIT, 'examples', 'demo'), D)
CFG = ['--config', os.path.join(D, 'brand.yaml')]; DATA = ['--data', D]
S = lambda n: os.path.join(KIT, 'scripts', n)
EX = os.path.join(D, 'exports')
steps = [
    ('第0-3步 建表/校验', [S('build_tables.py'), *DATA, *CFG, '--init']),
    ('第1-2步 收件箱入库（手动提供模式）', [S('ingest_posts.py'), *DATA]),
    ('第4步 文案事实校验', [S('check_copy.py'), *CFG, '--copy', os.path.join(D, 'drafts/D001/copy.md'), '--pages', os.path.join(D, 'drafts/D001/pages.yaml')]),
    ('第5步 出图（主版 A）', [S('render_post.py'), *CFG, '--layout', os.path.join(D, 'layout.yaml'), '--draft', os.path.join(D, 'drafts/D001')] + (['--only', 'cover'] if a.fast else [])),
    ('第5步 出图（套系 B）', [S('render_post.py'), *CFG, '--layout', os.path.join(D, 'layout.yaml'), '--draft', os.path.join(D, 'drafts/D001'), '--variant', 'B', '--only', 'cover']),
    ('第7步 发布队列：人工发布后回填（虚构笔记ID）', [S('ledger.py'), *DATA, *CFG, 'queue', '--draft', 'D001', '--status', '已发布', '--note-id', 'DEMO-NOTE-0001']),
    ('第8步 数据回收（聚光导出 + 自然流量）', [S('recover_juguang.py'), *CFG, *DATA, '--plan', os.path.join(EX, '计划-列表数据_DEMO_虚构.csv'),
                                     '--creative', os.path.join(EX, '创意-数据_DEMO_虚构.csv'), '--range', '2026-08-01 ~ 2026-10-31',
                                     '--organic', os.path.join(EX, '笔记数据_DEMO_虚构.csv')]),
    ('第9步 投流 A/B 方案', [S('ab_test.py'), *CFG, *DATA, 'plan', '--draft', 'D001', '--variant', 'A=主版 涂鸦地图', '--variant', 'B=套系B 白字描边',
                           '--variant', 'D=真人出镜', '--budget', '1500']),
    ('第10步 模拟投流（历史计划扮演 A/B/D）', [S('recover_juguang.py'), *CFG, *DATA, '--sim', '--draft', 'D001', '--range', '模拟 2026-11-01 ~ 2026-11-14',
                                     '--proxy', 'A=久坐党救星｜第一次上普拉提就爱了|久坐党救星｜第一次上普拉提就爱了2',
                                     '--proxy', 'B=下班后的45分钟｜城市里的放松角落|下班后的45分钟｜城市里的放松角落2',
                                     '--proxy', 'D=教练手把手｜普拉提新手第一课']),
    ('第10步 复盘判定 + 回写提议', [S('ab_test.py'), *CFG, *DATA, 'verdict', '--draft', 'D001', '--sim', '--write-back',
                              '--cover', f"A={os.path.join(D, 'drafts/D001/out/P01.png')}", '--cover', f"B={os.path.join(D, 'drafts/D001/out_B/P01.png')}"]),
    ('收尾 重建总表', [S('build_tables.py'), *DATA, *CFG]),
]
for title, cmd in steps:
    print(f'\n========== {title} =========='); sys.stdout.flush()
    r = subprocess.run([sys.executable] + cmd)
    if r.returncode != 0:
        sys.exit(f'✗ 失败：{title}（退出码 {r.returncode}）')
print(f'\n✓ demo 跑通。看结果：{D}/drafts/D001/out/preview.png、{D}/out/数据回收_总结.png、{D}/sim/out/复盘_D001.png、{D}/out/资产总表.xlsx')
