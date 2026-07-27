# Research HTML Archive

This repository publishes standalone HTML research notes and visualizations with GitHub Pages.

Public site:

- https://yzbcs.github.io/research/

## How It Works

- Put each standalone `.html` file in the `pages/` directory (the root `index.html` is the site entry).
- Add an index comment near the top of each HTML file:

```html
<!-- index: Page Title | 2026-05-31 | Short description shown on the index page -->
<!DOCTYPE html>
<html>
...
</html>
```

- `scripts/gen_index.py` scans `pages/*.html` and regenerates the root `index.html` entry.
- The GitHub Actions workflow runs on every push to `main`, generates the index, and deploys the whole repository to GitHub Pages.

## Add A New HTML Page

Clone once:

```bash
git clone https://github.com/yzbcs/research.git
cd research
```

Add or copy your HTML file into the repository root:

```bash
cp /path/to/my_page.html pages/my_page.html
python3 scripts/gen_index.py
git add pages/my_page.html index.html
git commit -m "Add my research page"
git push
```

After GitHub Actions finishes, open:

```text
https://yzbcs.github.io/research/pages/my_page.html
```

The index page is:

```text
https://yzbcs.github.io/research/
```

## Optional Helper Script

You can also use the helper script after cloning the repo:

```bash
python3 scripts/publish_html.py /path/to/my_page.html --title "My Page" --description "Short summary"
```

The script copies the file into the root, inserts an index comment if missing, regenerates `index.html`, and prints the git commands to run.

## GitHub Pages Setup

This repository is configured for the GitHub Actions deployment style. If the site does not appear after the first push, check:

1. GitHub repository page -> Settings -> Pages.
2. Build and deployment -> Source: GitHub Actions.
3. Actions tab -> latest `Deploy Research Pages` run is green.

## Naming Tips

- Use simple lowercase filenames, for example `exp141_gem_papers.html`.
- Avoid spaces in filenames.
- Keep each HTML page self-contained when possible.
