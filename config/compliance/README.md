# 行业合规起步包（compliance profiles）

`brand.yaml` 里写 `compliance.profile: <文件名>`（不带 .yaml），`check_copy.py` 就会自动加载对应的起步包。这些起步包是**起点，不是法律意见**：上线前请让合规审核人对照最新法规补充。
- `banned`：违禁词，逐词匹配（会跳过 `allow` 里的词，比如“第一次”不会被“第一”误拦）。
- `banned_patterns`：正则，用来拦住效果暗示、资质编造这类变化多的说法。
- `required_disclaimers`：正文里必须出现的免责语，缺了就算“必须改”。
- `qualification_terms`：资质类说法（三甲、认证、进口……）。正文里出现时，必须能在 `brand.yaml` 的 `qualifications` 里找到原文。
- `story_rule: off`：不允许第一人称体验故事或患者口吻；“情景演绎”标注在这里不能当免责（对应风格锁 SL-G10 自动停用）。
- `disable_rules`：建表（`--init`）时，自动把这些通用风格锁规则标成“停用”。
- `extra_required`：额外的必问事实，并入 `config/required_facts.yaml` 的闸门。
现有起步包：医疗、医美、教育、金融、餐饮食品、通用（不受监管的行业用通用，或者不写）。
