# 字体（不随仓库分发，运行 `python scripts/fetch_fonts.py` 下载到本目录）

| 用途 | 字体 | 许可 | 下载 |
|---|---|---|---|
| 标题 / 小标题 | 站酷快乐体 ZCOOL KuaiLe | SIL OFL 1.1 | https://fonts.google.com/specimen/ZCOOL+KuaiLe （文件：https://github.com/google/fonts/raw/main/ofl/zcoolkuaile/ZCOOLKuaiLe-Regular.ttf） |
| 正文 / 标签 | 霞鹜文楷 LXGW WenKai（Medium） | SIL OFL 1.1 | https://github.com/lxgw/LxgwWenKai/releases |
| 数字 / 价格 / 强调 | 得意黑 Smiley Sans | SIL OFL 1.1 | https://github.com/atelier-anchor/smiley-sans/releases |

- OFL 允许免费商用、把字体用在图片里、再分发（需附许可、不能单独卖字体）。为了让仓库轻、也方便各家替换，这里默认不内置字体文件；如果你们内部仓库想内置，把 `.ttf` 和对应 `OFL.txt` 一起放进来即可（记得删掉 `.gitignore` 里的 `fonts/*.ttf`）。
- 换字体：改 `config/brand.yaml` 的 `brand.fonts`，只用确认可商用的字体（很多“免费字体”只限个人使用）。
- 没下载字体时脚本会回退到系统中文字体（Noto Sans CJK / 苹方 / 微软雅黑）并提示，能出图但不是最终效果。
