#!/usr/bin/env python3
"""Import an external Markdown document into this Hugo blog."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable


SOURCE_MD = "/home/lucas/Blogs/Documents/贝叶斯算法优化电路参数.md"
DEFAULT_CATEGORY = "模拟IC自动化设计"
DEFAULT_TAGS = ["模拟IC", "IC自动化设计", "AI Agent", "优化算法"]
DEFAULT_SERIES_PAGE = "content/analog-ic-automation.md"
CHINESE_NUMERALS = {
    1: "一",
    2: "二",
    3: "三",
    4: "四",
    5: "五",
    6: "六",
    7: "七",
    8: "八",
    9: "九",
    10: "十",
}


IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def split_tags(raw: str | None) -> list[str]:
    if not raw:
        return list(DEFAULT_TAGS)
    return [item.strip() for item in raw.split(",") if item.strip()]


def has_yaml_front_matter(text: str) -> tuple[bool, list[str], str]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return False, [], text
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return True, lines[1:index], "".join(lines[index + 1 :])
    return False, [], text


def yaml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def yaml_array(items: Iterable[str]) -> str:
    return "[" + ", ".join(yaml_string(item) for item in items) + "]"


def validate_date(value: str) -> str:
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        raise argparse.ArgumentTypeError("--date must use YYYY-MM-DD format")
    try:
        dt.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--date must be a valid calendar date") from exc
    return value


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--series-index must be a positive integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("--series-index must be a positive integer")
    return parsed


def parse_inline_yaml_array(value: str) -> list[str]:
    value = value.strip()
    if not (value.startswith("[") and value.endswith("]")):
        return []
    inner = value[1:-1].strip()
    if not inner:
        return []
    result: list[str] = []
    for part in inner.split(","):
        item = part.strip().strip("'\"")
        if item:
            result.append(item)
    return result


def parse_yaml_list_items(lines: list[str], start: int, base_indent: int) -> tuple[list[str], int]:
    items: list[str] = []
    index = start
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent <= base_indent:
            break
        match = re.match(r"^\s*-\s*(.*?)\s*$", line)
        if not match:
            break
        item = match.group(1).strip().strip("'\"")
        if item:
            items.append(item)
        index += 1
    return items, index


def parse_front_matter_fields(fm_lines: list[str]) -> dict[str, object]:
    fields: dict[str, object] = {}
    index = 0
    while index < len(fm_lines):
        line = fm_lines[index]
        match = re.match(r"^(\s*)([A-Za-z0-9_-]+)\s*:\s*(.*?)(\s*)$", line.rstrip("\n"))
        if not match:
            index += 1
            continue

        indent, key, value, _ = match.groups()
        key_lower = key.lower()
        base_indent = len(indent)
        if key_lower in {"categories", "tags", "series"}:
            items = parse_inline_yaml_array(value)
            if not value.strip():
                block_items, index = parse_yaml_list_items(fm_lines, index + 1, base_indent)
                items.extend(block_items)
            else:
                index += 1
            fields[key_lower] = items
        else:
            fields[key_lower] = value.strip().strip("'\"")
            index += 1
    return fields


def merge_unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def add_title_prefix(title: str, series_index: int | None, enabled: bool) -> str:
    if not enabled or series_index is None:
        return title
    prefix = CHINESE_NUMERALS.get(series_index)
    if not prefix:
        return title
    if re.match(r"^\s*[一二三四五六七八九十]、", title):
        return title
    return f"{prefix}、{title}"


def normalize_front_matter(
    fm_lines: list[str],
    *,
    title: str,
    title_forced: bool,
    date: str,
    date_forced: bool,
    category: str,
    tags: list[str],
    series: str | None,
    series_index: int | None,
) -> list[str]:
    output: list[str] = []
    seen = {
        "draft": False,
        "categories": False,
        "tags": False,
        "title": False,
        "date": False,
        "series": False,
        "weight": False,
    }

    index = 0
    while index < len(fm_lines):
        line = fm_lines[index]
        match = re.match(r"^(\s*)([A-Za-z0-9_-]+)\s*:\s*(.*?)(\s*)$", line.rstrip("\n"))
        if not match:
            output.append(line)
            index += 1
            continue

        indent, key, value, _ = match.groups()
        base_indent = len(indent)
        key_lower = key.lower()
        if key_lower == "draft":
            output.append(f"{indent}draft: false\n")
            seen["draft"] = True
            index += 1
        elif key_lower == "date":
            output.append(f"{indent}date: {date}\n" if date_forced else line)
            seen["date"] = True
            index += 1
        elif key_lower == "categories":
            output.append(f"{indent}categories: {yaml_array([category])}\n")
            seen["categories"] = True
            if not value.strip():
                _, index = parse_yaml_list_items(fm_lines, index + 1, base_indent)
            else:
                index += 1
        elif key_lower == "tags":
            existing = parse_inline_yaml_array(value)
            if not value.strip():
                block_items, index = parse_yaml_list_items(fm_lines, index + 1, base_indent)
                existing.extend(block_items)
            else:
                index += 1
            merged = list(existing)
            for item in tags:
                if item not in merged:
                    merged.append(item)
            output.append(f"{indent}tags: {yaml_array(merged)}\n")
            seen["tags"] = True
        elif key_lower == "series":
            if series:
                output.append(f"{indent}series: {yaml_array([series])}\n")
            else:
                output.append(line)
            seen["series"] = True
            if not value.strip():
                _, index = parse_yaml_list_items(fm_lines, index + 1, base_indent)
            else:
                index += 1
        elif key_lower == "weight":
            if series_index is not None:
                output.append(f"{indent}weight: {series_index}\n")
            else:
                output.append(line)
            seen["weight"] = True
            index += 1
        elif key_lower == "title":
            seen["title"] = True
            output.append(f"{indent}title: {yaml_string(title)}\n" if title_forced else line)
            index += 1
        else:
            output.append(line)
            index += 1

    if not seen["title"]:
        output.append(f"title: {yaml_string(title)}\n")
    if not seen["date"]:
        output.append(f"date: {date}\n")
    if not seen["draft"]:
        output.append("draft: false\n")
    if not seen["categories"]:
        output.append(f"categories: {yaml_array([category])}\n")
    if not seen["tags"]:
        output.append(f"tags: {yaml_array(tags)}\n")
    if series and not seen["series"]:
        output.append(f"series: {yaml_array([series])}\n")
    if series_index is not None and not seen["weight"]:
        output.append(f"weight: {series_index}\n")

    return output


def first_heading(text: str) -> str | None:
    for line in text.splitlines():
        match = re.match(r"^\s*#\s+(.+?)\s*$", line)
        if match:
            title = re.sub(r"[*_`]+", "", match.group(1)).strip()
            if title:
                return title
    return None


def safe_slug(title: str, content: str, today: str) -> str:
    ascii_title = title.encode("ascii", "ignore").decode("ascii")
    words = re.findall(r"[A-Za-z0-9]+", ascii_title.lower())
    slug = "-".join(words).strip("-")
    if len(slug) >= 6:
        return slug[:80].strip("-")
    digest = hashlib.sha1((title + "\n" + content).encode("utf-8")).hexdigest()[:6]
    return f"{today}-post-{digest}"


def copy_local_images(markdown: str, source_dir: Path, target_root: Path, slug: str, dry_run: bool) -> tuple[str, list[Path]]:
    copied: list[Path] = []
    image_dir = target_root / "static" / "images" / slug

    def replace(match: re.Match[str]) -> str:
        alt_text, raw_path = match.groups()
        if re.match(r"^(https?:)?//|^data:|^#|^/", raw_path):
            return match.group(0)

        image_source = (source_dir / raw_path).resolve()
        if not image_source.is_file():
            return match.group(0)

        image_target = image_dir / image_source.name
        copied.append(image_target)
        if not dry_run:
            image_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(image_source, image_target)
        return f"![{alt_text}](/images/{slug}/{image_source.name})"

    return IMAGE_PATTERN.sub(replace, markdown), copied


def build_hugo(root: Path) -> tuple[bool, str]:
    result = subprocess.run(
        ["hugo", "--minify"],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    index_ok = (root / "public" / "index.html").is_file()
    return result.returncode == 0 and index_ok, result.stdout


def parse_int_or_none(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value))
    except ValueError:
        return None


def post_matches_series(fields: dict[str, object], series_name: str) -> bool:
    categories = fields.get("categories")
    series = fields.get("series")
    return (
        isinstance(categories, list)
        and series_name in categories
        or isinstance(series, list)
        and series_name in series
    )


def update_series_page(root: Path, series_name: str) -> Path | None:
    if series_name != DEFAULT_CATEGORY:
        print(f"Series page update skipped: no page mapping for series {series_name!r}")
        return None

    posts: list[dict[str, object]] = []
    for post_path in sorted((root / "content" / "posts").glob("*.md")):
        text = post_path.read_text(encoding="utf-8")
        has_fm, fm_lines, body = has_yaml_front_matter(text)
        if not has_fm:
            continue
        fields = parse_front_matter_fields(fm_lines)
        if not post_matches_series(fields, series_name):
            continue

        title = str(fields.get("title") or first_heading(body) or post_path.stem)
        date = str(fields.get("date") or "")
        weight = parse_int_or_none(fields.get("weight"))
        posts.append(
            {
                "title": title,
                "date": date,
                "weight": weight,
                "url": f"/posts/{post_path.stem}/",
            }
        )

    posts.sort(
        key=lambda item: (
            item["weight"] is None,
            item["weight"] if item["weight"] is not None else 999999,
            str(item["date"]),
            str(item["title"]),
        )
    )

    page = root / DEFAULT_SERIES_PAGE
    lines = [
        "---\n",
        f"title: {yaml_string(series_name)}\n",
        f"date: {dt.date.today().isoformat()}\n",
        "draft: false\n",
        "---\n",
        "\n",
        f"# {series_name}\n",
        "\n",
        "这里按章节顺序整理模拟 IC 自动化设计系列文章。\n",
        "\n",
    ]
    if posts:
        for post in posts:
            date_text = f" - {post['date']}" if post["date"] else ""
            lines.append(f"- [{post['title']}]({post['url']}){date_text}\n")
    else:
        lines.append("暂无已发布文章。\n")

    page.write_text("".join(lines), encoding="utf-8")
    return page


def git_commit(root: Path, files: list[Path], message: str) -> None:
    relative_files = [str(path.relative_to(root)) for path in files]
    subprocess.run(["git", "add", *relative_files], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=root, check=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import a Markdown file into the Hugo blog.")
    parser.add_argument("source", nargs="?", help="External Markdown file path.")
    parser.add_argument("--category", default=DEFAULT_CATEGORY, help="Hugo category for the imported post.")
    parser.add_argument("--tags", help="Comma-separated tag list.")
    parser.add_argument("--slug", help="Safe URL slug and target Markdown file name.")
    parser.add_argument("--title", help="Override or set the post title.")
    parser.add_argument("--date", type=validate_date, help="Post date in YYYY-MM-DD format.")
    parser.add_argument("--series", help="Hugo series name, written as series: [name].")
    parser.add_argument("--series-index", type=positive_int, help="Positive integer chapter index, written as weight.")
    parser.add_argument("--title-prefix", action="store_true", help="Prefix title with Chinese chapter number when --series-index is set.")
    parser.add_argument("--update-series-page", action="store_true", help="Update the series landing page after import.")
    parser.add_argument("--dry-run", action="store_true", help="Show planned changes without writing files.")
    parser.add_argument("--commit", action="store_true", help="Create a local git commit after a successful import.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite an existing target post file.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = repo_root()
    source = Path(args.source or SOURCE_MD).expanduser().resolve()
    category = args.category
    tags = split_tags(args.tags)
    today = dt.date.today().isoformat()
    requested_date = args.date

    if not source.is_file():
        print(f"ERROR: source Markdown does not exist: {source}", file=sys.stderr)
        return 2

    original = source.read_text(encoding="utf-8")
    has_fm, fm_lines, body = has_yaml_front_matter(original)
    fields = parse_front_matter_fields(fm_lines) if has_fm else {}
    existing_title = str(fields.get("title") or "") if fields.get("title") else None
    existing_date = str(fields.get("date") or "") if fields.get("date") else None
    base_title = args.title or existing_title or first_heading(body) or source.stem
    title = add_title_prefix(base_title, args.series_index, args.title_prefix)
    title_forced = bool(args.title or args.title_prefix or not existing_title)
    post_date = requested_date or existing_date or today
    date_forced = bool(requested_date)
    slug = args.slug or safe_slug(title, original, post_date)
    target = root / "content" / "posts" / f"{slug}.md"

    target_exists = target.exists()
    if target_exists and not args.overwrite and not args.dry_run:
        print(f"ERROR: target already exists: {target}", file=sys.stderr)
        print("Use --overwrite only after confirming that replacing it is intended.", file=sys.stderr)
        return 3
    if args.update_series_page and not args.series:
        print("ERROR: --update-series-page requires --series.", file=sys.stderr)
        return 5

    body, copied_images = copy_local_images(body, source.parent, root, slug, args.dry_run)
    if has_fm:
        new_fm = normalize_front_matter(
            fm_lines,
            title=title,
            title_forced=title_forced,
            date=post_date,
            date_forced=date_forced,
            category=category,
            tags=tags,
            series=args.series,
            series_index=args.series_index,
        )
    else:
        new_fm = [
            f"title: {yaml_string(title)}\n",
            f"date: {post_date}\n",
            "draft: false\n",
            f"categories: {yaml_array([category])}\n",
            f"tags: {yaml_array(tags)}\n",
        ]
        if args.series:
            new_fm.append(f"series: {yaml_array([args.series])}\n")
        if args.series_index is not None:
            new_fm.append(f"weight: {args.series_index}\n")
    new_text = "---\n" + "".join(new_fm).rstrip() + "\n---\n\n" + body.lstrip()

    print("Import summary")
    print(f"  Source Markdown: {source}")
    print(f"  Target post: {target}")
    print(f"  Title: {title}")
    print(f"  Date: {post_date}")
    print(f"  Category: {category}")
    print(f"  Tags: {', '.join(tags)}")
    if args.series:
        print(f"  Series: {args.series}")
    if args.series_index is not None:
        print(f"  Series index / weight: {args.series_index}")
    print(f"  Slug: {slug}")
    if target_exists:
        print("  Target exists: yes")
    if copied_images:
        print("  Local images:")
        for image in copied_images:
            print(f"    {image}")
    else:
        print("  Local images: none detected")

    if args.dry_run:
        print("  Dry run: no files written and Hugo build skipped")
        return 0

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(new_text, encoding="utf-8")
    series_page: Path | None = None
    if args.update_series_page:
        series_page = update_series_page(root, args.series)

    build_ok, build_output = build_hugo(root)
    article_dir = root / "public" / "posts" / slug
    article_file = article_dir / "index.html"
    article_generated = article_file.is_file()

    print("\nHugo build")
    print(f"  Success: {build_ok}")
    print(f"  public/index.html: {(root / 'public' / 'index.html').is_file()}")
    print(f"  Article page: {article_file if article_generated else 'not found'}")
    if build_output.strip():
        print("\nHugo output")
        print(build_output.rstrip())

    if not build_ok or not article_generated:
        print("ERROR: Hugo build failed or article page was not generated.", file=sys.stderr)
        return 4

    if args.commit:
        commit_files = [target]
        commit_files.extend(copied_images)
        if series_page:
            commit_files.append(series_page)
        git_commit(root, commit_files, f"Import blog post: {title}")
        print("\nLocal commit created. No push was performed.")

    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    ).stdout.strip() or "<current-branch>"

    print("\nNext manual commands")
    print(f"  cd {root}")
    print("  git status")
    print("  git diff --stat")
    print("  git add content/posts")
    if series_page:
        print(f"  git add {series_page.relative_to(root)}")
    if copied_images:
        print(f"  git add static/images/{slug}")
    print('  git commit -m "Import blog post"')
    print(f"  git push origin {branch}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
