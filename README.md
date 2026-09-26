# 博客维护

本站继续使用 Hugo、`hugo-blog-awesome` 和 GitHub Pages。文章统一放在 `content/posts/`，使用 YAML front matter。

## 发布文章

- **网页后台**：打开 [Pages CMS](https://app.pagescms.org/)，用 GitHub 登录，授权访问 `LucasAnalogGit/LucasAnalogGit.github.io`，选择 `master` 分支和“文章”。新建文章时填写标题、日期、分类、标签；属于系列的文章填写 `series` 和正整数 `weight`。新文章默认是草稿，检查完成后关闭“草稿”并保存。Pages CMS 提交到 `master` 后，现有 GitHub Actions 会构建并部署网站。
- **本地 Markdown**：直接在 `content/posts/` 编辑文章并推送到 `master`；也可以继续使用 [`scripts/import_md_to_blog.py`](scripts/import_md_to_blog.py)，用法见 [`scripts/README_import_md.md`](scripts/README_import_md.md)。两种方式写入同一目录。

新文章创建时，建议在 Pages CMS 的文件名输入框填写稳定的英文短名（例如 `my-new-post.md`）。URL 由文件名决定，标题修改不会改 URL；后台也已关闭现有文章的重命名操作。

图片在 Pages CMS 媒体库上传和管理，文件写入 `static/images/`，正文使用 `/images/...` 路径。正文编辑器可切换到 **Source** 模式，带有 LaTeX、Hugo shortcode 或复杂代码块的文章建议用此模式编辑并检查生成的 Markdown。主题已有 KaTeX 支持；需要数学公式的文章可在 front matter 加 `math: true`，Pages CMS 会保留未配置的 front matter 字段。手动维护的系列导航页 `content/analog-ic-automation.md` 不会由 CMS 自动更新；新的系列归档位于 `/series/`，按 `weight` 排序。

## 项目级扩展位置

- `layouts/`：页面模板；当前 `layouts/series/term.html` 负责系列排序。
- `layouts/partials/`：搜索、评论等跨页面片段。`custom-head.html` 已接入主题的扩展点，需要样式时可加载下述 CSS 文件。
- `layouts/shortcodes/`：正文中的项目卡片、论文卡片等复用组件，需要时创建。
- `assets/`：项目自己的 CSS、JavaScript 等源文件。需要样式时创建 `assets/css/custom.css`，会由 `custom-head.html` 自动引入。

不要直接改 `themes/hugo-blog-awesome/`。本地运行 `hugo --minify` 检查构建；部署由 `.github/workflows/hugo.yaml` 处理。
