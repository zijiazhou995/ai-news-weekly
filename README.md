# AI 新闻资讯半自动工作台

这个目录里是一套每周四可用的半自动流程：脚本自动抓取候选资讯、按你的规则打分去重，然后生成一份 Markdown 草稿。你只需要检查来源、删掉不合适的条目，再把“可直接复制版”稍作润色即可。

## 每周怎么用

1. 抓取并生成草稿，同时更新网站：

```bash
python3 -B weekly_ai_news.py run
```

2. 打开网站：

```bash
automation/serve_site.sh
```

然后访问：

```text
http://localhost:8765/
```

3. 点击首页里的日期区间，例如 `6.11-6.18`，进入当周新闻页。

4. 如果需要看 Markdown 草稿，打开输出文件：

```text
outputs/年份-W周-ai-news-draft.md
```

5. 先看“可直接复制版”，再核验“精选短讯（带来源和评分）”里的链接。

6. 需要更正式的表述时，把精选短讯复制给大模型，并使用：

```text
prompts/rewrite_prompt.md
```

## 手动补充重要资讯

如果你在微信、官网或群里看到重要信息，直接加到手动入口：

```bash
python3 weekly_ai_news.py add --date 6月11日 --company 阿里云 --title "阿里云发布开源工具“秒悟 Meoo CLI”" --url "https://example.com" --summary "该工具实现本地 AI 项目一键部署上线，可自动完成数据库配置、登录与发布。"
```

也可以运行交互式录入：

```bash
python3 weekly_ai_news.py add
```

手动补充会写入：

```text
inbox/manual_items.jsonl
```

阿里、电商、微信开放平台这类来源经常没有稳定 RSS，建议每周四先快速扫一遍：

```text
inbox/watchlist.md
```

## 调整筛选口径

主要配置在：

```text
config/settings.json
```

常改的字段：

- `min_score`：分数越高越严格。默认 6。
- `max_items`：最终精选条数。默认 8。
- `priority_companies`：重点关注公司，目前偏阿里系。
- `ecommerce_keywords`：电商、商家、营销、支付等关键词。
- `model_update_keywords`：用于排除纯模型更新。
- `sources`：AIbase、新闻搜索、RSS 和 Google News 查询源。

说明：AIbase 新闻页已经默认启用。`config/settings.json` 里也保留了 Bing News 和 Google News 查询源，但它们返回不稳定，所以默认关闭。需要再次尝试时，把对应源的 `enabled` 改为 `true` 即可。

## 常用命令

只抓候选：

```bash
python3 -B weekly_ai_news.py fetch
```

只根据已有候选生成草稿：

```bash
python3 -B weekly_ai_news.py draft
```

降低筛选阈值，找更多候选：

```bash
python3 -B weekly_ai_news.py draft --min-score 5
```

查看当前来源：

```bash
python3 -B weekly_ai_news.py sources
```

启动本地网站：

```bash
automation/serve_site.sh
```

换一个端口启动：

```bash
automation/serve_site.sh 8899
```

## 自动定时

已提供 macOS `launchd` 模板和安装脚本：

```text
automation/com.matchaaa.weekly-ai-news.plist.template
automation/install_launchd.sh
automation/uninstall_launchd.sh
```

如果想让电脑每周四 9:30 自动生成草稿，运行：

```bash
automation/install_launchd.sh
```

不想继续自动跑时，运行：

```bash
automation/uninstall_launchd.sh
```

定时任务不会自动发送消息，只会在 `outputs/` 里生成草稿，保留人工确认这一步。

## 发布到 GitHub Pages

项目已配置 GitHub Actions：每次把 `main` 分支推送到 GitHub 后，会自动把 `site/` 目录发布为 GitHub Pages。

首次发布：

```bash
git add .
git commit -m "Build weekly AI news site"
git remote add origin https://github.com/你的用户名/你的仓库名.git
git push -u origin main
```

然后到 GitHub 仓库：

1. 打开 `Settings`。
2. 进入 `Pages`。
3. `Build and deployment` 选择 `GitHub Actions`。
4. 等 `Actions` 里的 `Deploy GitHub Pages` 跑完。

发布成功后，网站地址通常是：

```text
https://你的用户名.github.io/你的仓库名/
```

之后每周更新：

```bash
python3 -B weekly_ai_news.py run
git add outputs site data/site_weeks.json
git commit -m "Update weekly AI news"
git push
```

## 这个工具会做什么

- 抓取配置里的 AIbase、新闻搜索、RSS 和 Google News 查询。
- 合并你手动补充的候选。
- 根据“知名公司、阿里/电商优先、产品/功能发布、非模型更新”打分。
- 自动按链接和关键事件去重。
- 输出“可直接复制版”“精选短讯”“候选池”“自动排除项”四部分。
- 同步生成 `site/index.html` 和 `site/weeks/年份-W周.html`，作为本地网站内容。

## 边界说明

国内很多官方来源没有稳定 RSS，微信文章也不适合完全自动抓取，所以这个版本保留了手动补充入口。实际使用时，脚本负责把大部分候选先捞出来，你负责最后判断哪些值得进入周报。
