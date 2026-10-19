# 小红书内容工作流工具包（任何行业 · 任何 agent）

这个工具包把“拆爆款 → 出图出文案 → 专家把关 → 发布 → 回收投流数据 → A/B 测试 → 复盘回写”做成一个闭环，每一篇都按上一篇的数据和专家意见改进。
它来自一个线下门店品牌的实战案例，已经去掉了行业和品牌信息。餐饮、美业、健身、教育、零售、本地生活都能用。

## 30秒看懂
```
你：回答 5 个问题（行业和品牌 / 卖什么和价格 / 在哪 / 目标顾客 / 有没有聚光；共 9 项事实）
        │  约 10 分钟
        ▼
第一篇草稿首图 + 文案（照着你给的参考图改）
        │
        ▼
 ┌─ 1 拆对标帖 → 2 拆自有帖 → 3 风格锁（以后每篇都要遵守的规矩）
 │        │
 │        ▼
 │  4 出文案（自动核对事实）→ 5 照参考图出图 → 6 专家评审 👤
 │        │
 │        ▼
 │  7 你亲自发布 👤 → 8 回收数据（点击率 / 留资成本）→ 9 投流 A/B 方案 👤 定预算
 │        │
 │        ▼
 └── 10 复盘：赢的做法写回风格锁（专家确认 👤）→ 下一篇更好
```
- 👤 是人工关卡：只有这几处会停下来等你拍板，其余 agent 自动往下做。
- 不知道走到哪一步了？运行 `python scripts/xhs.py status`，会用 3 行告诉你当前步骤、还差什么、下一步做什么。
- 出图只有两种方式：**给参考图（推荐）**，或者**不给参考图（极度不推荐，审美会很差）**。
- 简化的只是沟通方式，拆解、校验和质量关卡一个都不少。
- 该了解的信息一定会问清，只是到需要的那一步才问。价格、包含项、门店、能说的话、人脸规则、评审人这些事实没问清，评审和发布都过不去（`config/required_facts.yaml`）。

**能做到的效果**
1. **对标帖、自有帖收集和拆解**：
   - 收集有两种方式：**A 手动提供**（截图、图片、正文，任何 agent 都行）；**B 专用小号自动搜集**（能控制浏览器的 agent 用你提供的研究小号按关键词搜索、保存）。
   - 两种方式都进同一个收件箱，再由 `ingest_posts.py` 入库。
   - 拆解按 `templates/拆解模板.md`（沿用原案例用户自己的报告结构），写进可筛选的资产表（CSV / xlsx，可导入飞书多维表）。
2. **照着你给的参考图做针对性改编**：没有参考图就不出图，除非你看过“审美会非常差”的警告并二次确认。换成品牌色、三款免费商用字体、门店路线节点、已确认的价格和卖点。可以出 A/B 套系；照片里的人脸可以打码、贴纸或 AI 换脸（换脸必须标注）。
3. **专家人工评审**：每条意见原话入库，抽象成规则写进“风格锁”，下一篇自动遵守。
4. **发布队列**：发布由人来做，系统登记笔记ID，并提醒 AI 标注。
5. **数据回收**：读取聚光导出（自然流量可选），把计划关联到帖子，算出基线、及格线和优秀线，生成帖子成绩单。
6. **投流 A/B 方案**：按目标线定门槛、预算和止损线，规定计划命名，回收时自动关联。
7. **没有聚光也能走完**：数据回收、A/B 和复盘自动改用自然流量口径（按收藏率判），也可以用历史帖子做模拟演练。
8. **受监管行业护栏**：医疗、医美、教育、金融有合规起步包（`config/compliance/`），检查违禁句式、必带免责语和资质出处。
9. **投流复盘**：CPL 定胜负、CTR 为辅，过门槛才下结论；结论写回风格锁，专家确认后生效。没有真实数据时，可以用 `--sim` 模拟走通流程。

## 快速开始（5 分钟）
```bash
git clone https://github.com/wwaa34682-lab/xhs-workflow-kit.git && cd xhs-workflow-kit
python3 -m venv .venv && source .venv/bin/activate     # 必须用虚拟环境（系统 Python 常因 PEP 668 拒绝 pip install）；Windows: .venv\Scripts\activate
pip install -r requirements.txt
python scripts/fetch_fonts.py                           # 下载三款 OFL 免费商用字体（约 30MB）
python scripts/run_demo.py                              # 用虚构 demo 跑通全流程，结果在 demo_run/
```
然后打开你的 agent，在仓库目录里说：**“按 AGENTS.md 开始，帮我给我的品牌建档。”** agent 只问 5 个问题，约 10 分钟给你看第一篇草稿，再一步步带你走完 10 步。agent 怎么跟你说话，见 `docs/交互规范.md`：每次先给结果，一次只问一个问题，你回复数字就行。

## 在不同 agent 里使用
| Agent | 怎么装 | 入口 |
|---|---|---|
| **Codex**（CLI / IDE） | 在仓库目录里启动 Codex | 自动读取 `AGENTS.md` |
| **Claude Code** | 在仓库目录里启动；也可以把 `skills/xhs-workflow/` 复制到 `~/.claude/skills/` | `CLAUDE.md` 会导入 `AGENTS.md`；技能入口是 `SKILL.md` |
| **Cursor** | 用 Cursor 打开仓库 | 自动读取 `AGENTS.md`；也可以在对话里 @AGENTS.md |
| **Grok Bot** | 把仓库放到 Grok Bot 的电脑上（git clone 或上传 zip），告诉它路径 | 让它“读 AGENTS.md 按步骤执行” |
| 其他（Gemini CLI、Cline、Aider、OpenClaw……） | 只要能读文件、能运行 Python 就行 | 第一句话说“先读 AGENTS.md” |

收集模式 B 还需要 agent 能控制浏览器（例如 Grok Bot、Claude Code 的浏览器工具、Cursor 的浏览器）。没有这个能力的 agent，第 1、2 步用模式 A。

agent 只需要两个能力：**读写本地文件**、**运行 Python 命令**。所有规则都写在纯文本文件里，不依赖任何 agent 的专有功能。

## 需要准备什么
- Python 3.9 及以上（Windows、macOS、Linux 都可以）。
- 必装依赖：numpy、Pillow、PyYAML、openpyxl（见 `requirements.txt`）。
- 可选：
  - `opencv-contrib-python-headless`：油画质感更好；
  - `opencv-python-headless`：打码和贴纸；
  - `insightface` + `onnxruntime` + 模型：AI 换脸。**注意**：常见的换脸模型只许非商业使用，商用前请自己确认许可，见 `scripts/face_swap.py`。
- 业务资料：
  - 品牌事实（问答时提供）；
  - 5–20 篇对标帖：手动提供，或者准备一个研究小号；
  - 自有帖；
  - 至少 1 张你觉得好看的参考图（出图时必须要；不给也行，但审美会非常差）；
  - 自有实拍照片；
  - 聚光导出 CSV（没有聚光也可以，用自然流量数据）。
- 一位**专家评审人**（老板或品牌负责人），这是人工关卡，不能省。

## 目录
```
AGENTS.md / CLAUDE.md / skills/xhs-workflow/SKILL.md   给 agent 的总说明（内容同源）
onboarding/开始使用.md                                第 00 步：建档问答 → config/brand.yaml
steps/01…10-*.md                                      每一步的目标、输入、提示词、产出、人工关卡、完成标准
config/brand.example.yaml  layout.example.yaml        品牌事实模板、模板改编参数模板
config/examples/餐饮.yaml 美业.yaml 健身.yaml           虚构行业示例
templates/拆解模板.md  拆解模板_填写示例.md          对标/自有拆解模板（字段→列名映射）
templates/参考图拆解清单.md  快速起步/                 出图前的参考图拆解清单；第一篇草稿骨架
config/layouts/  config/compliance/  required_facts.yaml  出图预设；行业合规起步包；必问事实清单
templates/tables/*.csv  风格锁_通用起步.csv  字段说明.md  空表结构、通用规则、字段说明
docs/交互规范.md  注意事项.md  泛化说明.md          agent 怎么跟人说话（必读）；合规与风险；从案例泛化了什么
scripts/                                              xhs（status/next/quickstart/card/new）  ingest_posts  fill_breakdown  build_tables  organic  check_copy  render_post(+subject)  face_swap
                                                      ledger  recover_juguang  ab_test  fetch_fonts  run_demo
examples/demo/                                        虚构的端到端 demo（配置、收件箱、表、聚光导出、稿件）
data/  （自己创建，已被 .gitignore 排除）              你的真实数据：tables/ raw/ exports/ drafts/ out/ sim/
```

## 注意事项（全文见 `docs/注意事项.md`）
- 模式 B 只能用**专门用来研究的小号**，不能用品牌主运营账号：
  - 登录、扫码、验证码都由你本人完成；
  - agent 只用普通网页，不碰 cookie 和验证码，每次 ≤30 篇且要有停顿；
  - 小号可能被平台限制，风险需要你事先接受；
  - agent 不能控制浏览器时，用模式 A。
- 不编造事实：没确认的写【待业务确认】，`check_copy.py` 和出图脚本都会拦住。
- 不代发、不代投：发布、建计划、花钱全部由人操作。
- 对标素材只做研究，不商用。
- 用了 AI 换脸或 AI 生成内容，发布时必须勾选「含AI生成内容」。
- 真实数据放在 `data/`，不进 git。分享仓库前跑一遍 `git status`，确认没有数据、照片、导出文件和账号信息。

## 许可
代码和文档：MIT（见 `LICENSE`）。字体不随仓库分发，各自按 SIL OFL 1.1 许可（见 `fonts/README.md`）。
