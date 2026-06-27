# Markdown 文章导入脚本

`scripts/import_md_to_blog.py` 用于把外部 Markdown 文档导入 Hugo 博客的 `content/posts/`，自动补全或修正 Hugo front matter，并在本地执行 `hugo --minify` 做构建检查。

脚本不会执行 `git push`，也不会写入任何 GitHub token、password、SSH key 或 credential。默认也不会 commit。

## 基本用法

从命令行传入 Markdown 文件路径：

```bash
cd /home/lucas/Blogs/LucasAnalogGit.github.io
python3 scripts/import_md_to_blog.py /home/lucas/Blogs/Documents/贝叶斯算法优化电路参数.md
```

也可以直接修改脚本顶部的 `SOURCE_MD`，然后运行：

```bash
cd /home/lucas/Blogs/LucasAnalogGit.github.io
python3 scripts/import_md_to_blog.py
```

## 指定分类、标签、slug 和标题

默认分类为 `模拟IC自动化设计`，默认标签为 `模拟IC, IC自动化设计, AI Agent, 优化算法`。

```bash
python3 scripts/import_md_to_blog.py /home/lucas/Blogs/Documents/贝叶斯算法优化电路参数.md \
  --category "模拟IC自动化设计" \
  --tags "模拟IC,IC自动化设计,AI Agent,优化算法" \
  --slug bayesian-optimization-circuit-parameters \
  --title "贝叶斯算法优化电路参数"
```

建议为中文标题文章显式传入英文 slug，避免中文 URL 或自动 fallback 文件名不够直观。

## 指定发布日期

使用 `--date` 明确设置文章发布日期。日期必须是 `YYYY-MM-DD` 格式：

```bash
python3 scripts/import_md_to_blog.py /path/to/article.md \
  --title "文章标题" \
  --slug article-slug \
  --date 2026-06-27
```

如果不传 `--date`，新文章默认使用当前日期；已有 front matter 的文章会保留原有 `date`。

## 导入系列文章

使用 `--series` 写入 Hugo front matter：

```yaml
series: ["模拟IC自动化设计"]
```

使用 `--series-index` 写入章节顺序：

```yaml
weight: 3
```

示例：

```bash
python3 scripts/import_md_to_blog.py /path/to/article.md \
  --title "基于 Spectre/OCEAN 的模拟电路自动仿真流程" \
  --slug spectre-ocean-automatic-simulation-flow \
  --category "模拟IC自动化设计" \
  --series "模拟IC自动化设计" \
  --series-index 3 \
  --date 2026-06-27
```

## 自动添加中文章节标题

传入 `--title-prefix` 时，脚本会根据 `--series-index` 给标题添加中文章节前缀：

```bash
python3 scripts/import_md_to_blog.py /path/to/article.md \
  --title "基于 Spectre/OCEAN 的模拟电路自动仿真流程" \
  --series-index 3 \
  --title-prefix
```

生成的标题为：

```yaml
title: "三、基于 Spectre/OCEAN 的模拟电路自动仿真流程"
```

如果标题已经以 `一、`、`二、`、`三、` 等前缀开头，脚本不会重复添加。

## 更新系列专栏页

使用 `--update-series-page` 自动扫描 `content/posts/`，把 categories 或 series 中包含 `模拟IC自动化设计` 的文章按 `weight` 从小到大列入：

```text
content/analog-ic-automation.md
```

没有 `weight` 的文章会排在已有 `weight` 的文章之后。

完整示例：

```bash
python3 scripts/import_md_to_blog.py \
  "/home/lucas/Blogs/Documents/3.基于Spectre_OCEAN的模拟电路自动仿真流程.md" \
  --title "基于 Spectre/OCEAN 的模拟电路自动仿真流程" \
  --slug spectre-ocean-automatic-simulation-flow \
  --category "模拟IC自动化设计" \
  --series "模拟IC自动化设计" \
  --series-index 3 \
  --title-prefix \
  --date 2026-06-27 \
  --tags "模拟IC,IC自动化设计,AI Agent,Spectre,OCEAN,Virtuoso,EDA自动化" \
  --update-series-page
```

## Dry Run

只查看将要导入的目标路径、标题、分类和标签，不写文件，不执行 Hugo 构建：

```bash
python3 scripts/import_md_to_blog.py /home/lucas/Blogs/Documents/贝叶斯算法优化电路参数.md \
  --slug bayesian-optimization-circuit-parameters \
  --dry-run
```

## 本地 Commit

默认不 commit。如果确认导入结果正确，可以手动提交：

```bash
cd /home/lucas/Blogs/LucasAnalogGit.github.io
git status
git diff --stat
git add scripts/import_md_to_blog.py scripts/README_import_md.md content/posts
git commit -m "Import Markdown blog post"
git push origin $(git branch --show-current)
```

脚本也提供 `--commit`，但只会执行本地 `git commit`，不会 push：

```bash
python3 scripts/import_md_to_blog.py /path/to/article.md --slug my-post --commit
```

## 图片处理

脚本会保守检查 Markdown 图片语法 `![alt](path/to/image.png)`。只有当图片路径是本地相对路径且文件确实存在时，才会复制到：

```text
static/images/<slug>/
```

并把文章中的图片路径改为：

```markdown
![alt](/images/<slug>/image.png)
```

网络图片、站内绝对路径、data URL 和不存在的本地路径不会被改写。
