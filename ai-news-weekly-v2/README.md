# AI News Weekly v2

一个从零开始的新项目，用 AIbase 新闻详情页生成“本周 AI 资讯”静态网站。

## 最小版本能力

- `crawler`：从 `https://www.aibase.com/zh/news` 获取最近新闻 ID，并逐条抓取 AIbase 详情页。
- `extractor`：从详情页提取标题、日期、详情页 URL、导语段、正文首段、标签。
- `editor`：默认使用规则过滤；如果配置 `OPENAI_API_KEY`，`--editor auto` 会尝试调用 OpenAI-compatible Chat Completions 做 AI 编辑判断。
- `verifier`：二次校验 URL、日期、标题、摘要开头和正文关联，排除不合格内容。
- `site`：生成 `site/index.html`、`site/weeks.json` 和每周 JSON。

## 运行

```bash
cd /Users/matchaaa/Documents/ai新闻资讯/ai-news-weekly-v2
./scripts/run_weekly.sh --start 2026-06-23 --end 2026-06-29 --max-items 30
```

输出：

- 每周数据：`data/weeks/{start}_{end}.json`
- 原始详情页：`data/raw/{start}_{end}/`
- 网站：`site/index.html`

如果首页最近 20-30 条不足以覆盖目标周，可以手动补充 AIbase 详情页：

```bash
./scripts/run_weekly.sh --start 2026-06-23 --end 2026-06-29 --url https://www.aibase.com/zh/news/29235
```

## AI 编辑

默认无需依赖即可运行，编辑判断来源会标记为 `rules`。

如需 AI 编辑：

```bash
export OPENAI_API_KEY="..."
export OPENAI_MODEL="gpt-4.1-mini"
./scripts/run_weekly.sh --editor auto
```

也可以使用 OpenAI-compatible 地址：

```bash
export OPENAI_BASE_URL="https://api.openai.com/v1"
```

## 周期

当前默认窗口是运行日往前 6 天到运行日，适合每周四生成 `周五-周四` 的周报。也可以显式传入 `--start` 和 `--end`。

## 筛选口径

保留“更符合要求”“备选线索”“待确认”“排除原因”四类数据。页面只突出展示通过校验的“更符合要求”和“备选线索”，同时保留待确认与排除项，方便后续人工检查。
