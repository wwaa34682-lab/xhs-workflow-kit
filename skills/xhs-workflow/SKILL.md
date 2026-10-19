---
name: xhs-workflow
description: 小红书（Xiaohongshu/RED）内容闭环工作流，适用于任何行业。流程包括：收集（手动提供，或用专用小号在浏览器里收集）并拆解对标帖和自有帖，写入资产表；照着用户给的参考图针对性改编出首图和内页（没有参考图须二次确认）；专家人工评审，意见回写风格锁；用户自己发布；回收聚光广告数据，算出基线和目标线；做投流 A/B 方案；投流复盘后回写。用户提到小红书出帖、种草笔记、爆款拆解、聚光投流、投流复盘、风格锁时使用。
---

# 小红书内容工作流（技能入口）

> **必读：`docs/交互规范.md`。** 每次回复都要带进度标签、先给结果、一次只问一个问题（带编号选项和推荐默认）、只在关卡停下来等人。简化只作用于沟通方式，不得删减拆解字段、风格锁、校验或质量闸门。不知道当前在哪一步时，运行 `python scripts/xhs.py status`。

这个技能就是整个仓库。用法：
1. 把仓库放在本机任意位置（下文记作 `<kit>`）。在 `<kit>` 里先建虚拟环境（`python3 -m venv .venv && . .venv/bin/activate`，避免 PEP 668 报错），再运行 `pip install -r requirements.txt` 和 `python scripts/fetch_fonts.py`。
2. 读 `<kit>/AGENTS.md`。里面有总说明、铁律、10 步闭环和目录约定，以它为准。
3. 如果还没有 `<kit>/config/brand.yaml`，按 `<kit>/onboarding/开始使用.md` 的快速通道问 5 个问题，然后运行 `python scripts/xhs.py quickstart` 出第一篇草稿。
   之后每一轮先运行 `python scripts/xhs.py status`，或者用 `python scripts/xhs.py next` 看下一步。
4. 每一步按 `<kit>/steps/NN-*.md` 执行。所有命令都在 `<kit>` 目录下运行。

铁律摘要（全文见 AGENTS.md）：
- 不编造事实。不知道的写【待业务确认】。
- 专家评审、发布、建计划和花钱、让规则生效，都必须由人做决定。
- 必问事实（`config/required_facts.yaml`）是硬闸门：缺一项，评审通过和发布都会被拒绝。业务事实不给默认值。
- 出图前只给两个选项：1.【推荐·默认】给参考图，做针对性修改；2. 没有参考图（极度不推荐，警告后要二次确认）。`render_post.py` 没登记参考图就拒绝出图，除非加 `--no-reference-confirmed`。
- 对标素材只做研究。拆解字段按 `templates/拆解模板.md`。
- 帖子收集：A 手动提供（任何 agent）/ B 专用小号（只有能控制浏览器才能用；只用普通网页；用户本人登录；不碰 cookie 和验证码；每次 ≤30 篇且要有停顿；不用主运营号）。
- 用了 AI 换脸，必须标注「含AI生成内容」。
- 模拟数据不能用来改规则，也不能据此停投或放量。
- 文案和标签要给用户确认；第 5 步要做完内页、人脸处理和参考对比才算完成。
- 同一步缺多项事实时用 `xhs.py card` 发确认卡；第二篇用 `xhs.py new --reuse-refs`。
- `data/` 里是私有数据，不提交。

如果这个技能目录是被单独复制出来的（例如放到了 `~/.claude/skills/xhs-workflow/`），而 `<kit>` 在别处：先问用户 `<kit>` 在哪里，或者让用户从 GitHub 克隆这个仓库。
