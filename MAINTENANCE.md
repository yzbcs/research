# 后续维护教程

仓库地址：

- https://github.com/yzbcs/research

公开页面：

- https://yzbcs.github.io/research/

## 日常发布一个新的 HTML

第一次先克隆仓库：

```bash
git clone https://github.com/yzbcs/research.git
cd research
```

之后每次新增页面：

```bash
cp /path/to/your_page.html pages/your_page.html
python3 scripts/gen_index.py
git add pages/your_page.html index.html
git commit -m "Add your page"
git push
```

推送后，GitHub Actions 会自动部署。页面地址会是：

```text
https://yzbcs.github.io/research/pages/your_page.html
```

## 推荐的 HTML 头部注释

每个 HTML 文件顶部建议加一行索引用注释：

```html
<!-- index: 页面标题 | 2026-05-31 | 这段描述会显示在首页索引里 -->
```

如果没有这行注释，索引脚本会尝试读取 `<title>` 和 `<meta name="description">`。

## 用辅助脚本发布

在克隆好的仓库里运行：

```bash
python3 scripts/publish_html.py /path/to/your_page.html --title "页面标题" --description "页面简介"
```

脚本会：

1. 把 HTML 复制到 pages/ 目录。
2. 如果没有索引注释，就自动补一行。
3. 重新生成 `index.html`。
4. 打印接下来要运行的 `git add / commit / push` 命令。

也可以让脚本直接提交和推送：

```bash
python3 scripts/publish_html.py /path/to/your_page.html --title "页面标题" --description "页面简介" --commit --push
```

## 修改已有页面

直接编辑对应的 `.html` 文件，然后：

```bash
python3 scripts/gen_index.py
git add 修改的文件.html index.html
git commit -m "Update page"
git push
```

## 删除页面

```bash
rm pages/old_page.html
python3 scripts/gen_index.py
git add pages/old_page.html index.html
git commit -m "Remove old page"
git push
```

## GitHub Pages 设置

如果 `https://yzbcs.github.io/research/` 暂时打不开，检查：

1. 打开仓库 Settings -> Pages。
2. Build and deployment 的 Source 选择 `GitHub Actions`。
3. 打开 Actions 标签页，确认 `Deploy Research Pages` 是绿色成功状态。

第一次部署可能需要 1-3 分钟。

## 文件命名建议

- 使用小写英文、数字、下划线或短横线。
- 不要使用空格。
- 示例：`exp141_gem_papers.html`、`arr_2026_browser.html`。
