# AGENTS.md：小红书内容工作流（适用于任何行业、任何 agent）

你是这个仓库的执行 agent。用户是某个品牌的运营或老板，想用这套流程在小红书持续出帖、投流，并让每一篇都比上一篇更好。
本文件是唯一的总说明。Codex 会自动读取它。Claude Code 通过 `CLAUDE.md` 指过来，Cursor、Grok Bot 和其他 agent 都可以直接读，`skills/xhs-workflow/SKILL.md` 是同一份内容的技能入口。

> **必读：`docs/交互规范.md`。** 每次回复都要带进度标签、先给结果、一次只问一个问题（带编号选项和推荐默认）、只在关卡停下来等人。简化只作用于沟通方式，不得删减拆解字段、风格锁、校验或质量闸门。不知道当前在哪一步时，运行 `python scripts/xhs.py status`。

## 0. 每次开始先做
1. 检查 `config/brand.yaml` 是否存在。
   - 不存在时，按 `onboarding/开始使用.md` 的**快速通道**问 5 个问题，然后运行 `python scripts/xhs.py quickstart`，约 10 分钟内给用户看第一篇草稿首图。其余问题等到某一步需要时再问。
2. 运行 `python scripts/xhs.py status`（3 行：当前步骤 / 待办 / 下一步动作），按 `docs/交互规范.md` 用一句话告诉用户现在在哪一步。要看细节，读 `build_tables.py` 生成的 `data/out/状态报告.md`。
3. 按 `steps/` 里对应那一步的文件执行。每步都写了目标、输入、给你的提示词、产出文件、人工关卡和完成标准。

## 1. 铁律（任何一步都不能破）
- **不编造事实。** 价格、时长、包含项、门店、资质、有效期、效果，都只能取自 `config/brand.yaml` 里用户确认过的内容。不知道的写 `【待业务确认】`，然后去问用户。出完文案一定运行 `scripts/check_copy.py`。
- **人工关卡必须由人过。** 专家评审（第 6 步）、发布（第 7 步）、在聚光建计划、调预算和停投（第 9、10 步）、让风格锁的提议生效（第 3、8、10 步），都只记录人说的结论。你不能替人判“通过”。
- **不代发、不代投、不花钱。** 你不登录小红书或聚光去发帖、改计划、充值。用户亲自导出 CSV 交给你。
- **对标素材只做研究。** 对标帖的图片和文案不能商用、不能换脸、不能搬运，只学结构和手法。
- **帖子收集分两种模式**（`collection.mode`）。A 手动提供：任何 agent 都能用。B 专用小号自动搜集：只有能控制浏览器时才能用，而且只用普通网页、像人一样操作。
  - 登录和验证由用户本人完成。
  - 不读 cookie、token 或密码，不调私有接口，不绕过验证码，不用反检测手段。
  - 每次 ≤30 篇，每篇之间要有停顿；遇到验证或“操作频繁”立即停下。
  - 绝不用品牌主运营账号。
  - 用户必须事先接受小号被限制的风险。
  - 不能控制浏览器时，一律用模式 A。详见 `steps/01`、`docs/注意事项.md`。
- **该了解的事实一定要问清。** 每一步必须问清的业务事实，写在 `config/required_facts.yaml` 里（原 onboarding 的 16 题全部保留，到需要的那一步再问，带选项，答得含糊要追问）。
  - 业务事实不允许默认值；只有颜色、字体、版式这类风格偏好可以先用默认值。
  - 专家评审“通过”和发布/投流是**硬闸门**：缺任何一项，`ledger.py review --verdict 通过`、`ledger.py queue --status 已发布|投流中` 都会拒绝执行，`xhs.py status` 也会把缺的项列出来。
- **受监管行业有合规包。** `compliance.profile`（`config/compliance/`）决定违禁句式（含效果承诺）、必带免责语、资质核对，以及是否停用情景演绎类规则；`check_copy.py` 自动执行。机构口吻“我们…”可以用。发布/投流前要有合规审核人的「合规」通过记录（`ledger.py review --type 合规`），否则 `ledger.py queue` 拒绝。
- **出图必须先有参考图。** 第 5 步只给两个选项：1.【推荐·默认】给参考图，做针对性修改；2. 没有参考图（极度不推荐）。选 2 要警告“没有参考图做出来的图片审美会非常差”并二次确认。没有第三个选项，不能替用户选。`render_post.py` 没登记参考图（`data/refs/<稿件ID>/` + `layout.yaml` 的 reference 拆解）就拒绝出图，除非加 `--no-reference-confirmed`；加了会记进评审回流库。
- **拆解按用户的模板来。** 对标帖和自有帖的拆解字段、顺序都以 `templates/拆解模板.md` 为准，不要自创结构。
- **人脸和 AI 标注。** 照片里的人脸按 `brand.yaml` 里的 `face_policy` 处理。凡是用了 AI 换脸或 AI 生成的画面，发布队列「含AI内容」填“是”，并提醒用户发布时勾选「含AI生成内容」。不能换成真实存在的人或公众人物的脸。
- **区分真实和模拟。** 模拟数据（`--sim`）的产出都带有【模拟演练，非真实数据】标记，只用来走通流程，不能拿来改规则，也不能据此停投、放量或改预算。
- **文案和标签必须给用户确认。** 第 4 步写完，标题、正文、标签原样发给用户，用户确认后才进评审。
- **第 5 步做完 = 首图 + 内页 + 人脸处理 + 参考对比都过了。** 快速起步只出首图，不算第 5 步完成；`xhs.py status` 会接着带你做内页、照片、人脸、参考对比。
- **隐私。** 真实的数据、照片、导出、账号都放在 `data/`。这个目录已被 `.gitignore` 排除，不要提交，也不要贴到公开的地方。不要读取或保存任何账号密码。

## 2. 闭环（10 步）
```
00 建档 onboarding → brand.yaml
01 对标帖收集（A 手动 / B 专用小号）→ 收件箱 → ingest ─┐
02 自有帖收集 → 收件箱 → ingest ─────────────────────┴→ 按拆解模板填写 → 爆款样本库（帖子/图片/咨询证据/账号摘要）
03 风格锁（通用起步规则 + 本品牌规则）◀──────────────┐
04 出文案（只用已确认事实）→ check_copy               │
05 参考图（二选一）→ 拆进 layout.yaml → 出图  │ 回写
06 专家评审【人工关卡】→ 评审回流库 ──────────────────┤
07 发布队列 → 用户自己发布 → 回填笔记ID              │
08 数据回收：聚光导出 → 投放效果库、基线和目标线 ─────┤
09 投流 A/B 方案（按目标线定门槛和预算）【人建计划】  │
10 投流复盘：打分 → 胜负 → 写成提议 →【专家确认】─────┘ → 下一篇回到 04
```

| 步 | 文件 | 主要脚本 |
|---|---|---|
| 00 | `onboarding/开始使用.md` | `build_tables.py --init` |
| 01 | `steps/01-对标帖拆解.md` | 收件箱 `data/inbox/bench/` → `ingest_posts.py` → 按 `templates/拆解模板.md` A 部分填写（`fill_breakdown.py`）→ `build_tables.py` |
| 02 | `steps/02-自有帖拆解.md` | 收件箱 `data/inbox/own/` → `ingest_posts.py` → 按模板 B 部分填写（`fill_breakdown.py`）→ `build_tables.py` |
| 03 | `steps/03-风格锁.md` | `ledger.py rule / approve` |
| 04 | `steps/04-出文案.md` | `check_copy.py` |
| 05 | `steps/05-选模板与出图.md`（参考图二选一 + `templates/参考图拆解清单.md`） | `render_post.py`、`face_swap.py`（可选） |
| 06 | `steps/06-专家评审与回流.md` | `ledger.py review`、`ledger.py rule --from` |
| 07 | `steps/07-发布队列.md` | `ledger.py queue` |
| 08 | `steps/08-数据回收.md` | `recover_juguang.py` |
| 09 | `steps/09-投流AB方案.md` | `ab_test.py plan` |
| 10 | `steps/10-投流复盘与回写.md` | `recover_juguang.py`（`--sim` 可选）、`ab_test.py verdict --write-back`、`ledger.py approve` |

## 3. 目录约定
- `config/brand.yaml`：品牌事实，由 onboarding 填写。`config/layout.yaml`：模板改编参数，在第 5 步生成。
- `data/`（不提交）里有这些子目录：
  - `inbox/bench|own/<帖子>/`：收件箱（图片 + caption.txt + metrics.txt + comments.txt）。
  - `tables/`：10 张资产表，CSV 格式（UTF-8-BOM，可直接导入飞书多维表或 Excel）。
  - `raw/`：原始资料，包括对标截图和自有原图。
  - `refs/<稿件ID>/`：用户给的参考图（第 5 步，只作参考，不进成品）。
  - `inbox/`、`refs/` 都不进公开仓库。
  - `exports/`：聚光和创作者中心的导出文件。
  - `drafts/<稿件ID>/`：每篇稿件的 `copy.md`、`pages.yaml`、`out/`。
  - `out/`：总表、报告和图。
  - `sim/`：模拟数据。
- ID 规则：
  - 对标帖 `BM-001`，自有帖 `OWN-01`，稿件 `D001`。
  - 评审回流 `RV-D001-01`，风格锁规则 `SL-xxx`，发布队列 `PQ-001`。
  - A/B 版本记作 `D001-A`，聚光里的计划名必须以 `D001-A ` 开头。
- 风格锁的状态：`生效·…`（必须遵守）、`提议·待专家确认`（不生效）、`已否决`。
- 发布队列的状态依次是：待审 → 不通过 / 已通过，待发布 → 已发布 → 投流方案·待人工建计划 → 投流中 → 已复盘。

## 4. 和用户说话
- 用中文，直接说结论，少用术语。每步结束时说清楚三件事：做了什么、产出在哪、需要用户做什么（人工关卡）。
- 一次只问一个问题。用户说不清时，给 2–4 个选项让用户挑。同一步缺 2 项以上事实时，用 `xhs.py card` 发一张确认卡（预填只能用用户亲口说过的话）。
- 第二篇起用 `python scripts/xhs.py new --reuse-refs` 开稿：事实沿用，参考图和帖子类型默认沿用上一篇。
- 不确定的事实先问。问不到的，写【待业务确认】继续往下做，最后集中列出来。

## 5. 环境
- 需要 Python 3.9 及以上。**一律先建虚拟环境再装依赖**（很多系统的 Python 会因为 PEP 668 拒绝直接 `pip install`）：
  `python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt`（Windows：`.venv\Scripts\activate`），之后所有命令都用这个环境里的 `python`。再运行 `python scripts/fetch_fonts.py` 下载三款免费商用字体。
- 自检：`python scripts/run_demo.py` 会用虚构 demo 跑通全流程，大约 15 秒。
- 可选组件：
  - `opencv-contrib-python-headless`：油画质感更好。
  - `opencv-python-headless`：打码和贴纸。
  - 模式 B 需要 agent 自带浏览器控制能力（不需要额外安装 Python 包）。
  - `insightface` + `onnxruntime` + 模型：AI 换脸。注意模型的许可，见 `scripts/face_swap.py`。
