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


def yaml_array(items: Iterable[str]) -> str:
    escaped = [item.replace("\\", "\\\\").replace('"', '\\"') for item in items]
    return "[" + ", ".join(f'"{item}"' for item in escaped) + "]"


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


def normalize_front_matter(
    fm_lines: list[str],
    *,
    title: str | None,
    category: str,
    tags: list[str],
) -> list[str]:
    output: list[str] = []
    seen = {"draft": False, "categories": False, "tags": False, "title": False}

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
        elif key_lower == "title":
            seen["title"] = True
            output.append(f'{indent}title: "{title}"\n' if title else line)
            index += 1
        else:
            output.append(line)
            index += 1

    if title and not seen["title"]:
        output.append(f'title: "{title}"\n')
    if not seen["draft"]:
        output.append("draft: false\n")
    if not seen["categories"]:
        output.append(f"categories: {yaml_array([category])}\n")
    if not seen["tags"]:
        output.append(f"tags: {yaml_array(tags)}\n")

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

    if not source.is_file():
        print(f"ERROR: source Markdown does not exist: {source}", file=sys.stderr)
        return 2

    original = source.read_text(encoding="utf-8")
    has_fm, fm_lines, body = has_yaml_front_matter(original)
    title = args.title or first_heading(body) or source.stem
    slug = args.slug or safe_slug(title, original, today)
    target = root / "content" / "posts" / f"{slug}.md"

    target_exists = target.exists()
    if target_exists and not args.overwrite and not args.dry_run:
        print(f"ERROR: target already exists: {target}", file=sys.stderr)
        print("Use --overwrite only after confirming that replacing it is intended.", file=sys.stderr)
        return 3

    body, copied_images = copy_local_images(body, source.parent, root, slug, args.dry_run)
    if has_fm:
        new_fm = normalize_front_matter(fm_lines, title=args.title, category=category, tags=tags)
    else:
        new_fm = [
            f'title: "{title}"\n',
            f"date: {today}\n",
            "draft: false\n",
            f"categories: {yaml_array([category])}\n",
            f"tags: {yaml_array(tags)}\n",
        ]
    new_text = "---\n" + "".join(new_fm).rstrip() + "\n---\n\n" + body.lstrip()

    print("Import summary")
    print(f"  Source Markdown: {source}")
    print(f"  Target post: {target}")
    print(f"  Title: {title}")
    print(f"  Category: {category}")
    print(f"  Tags: {', '.join(tags)}")
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
    if copied_images:
        print(f"  git add static/images/{slug}")
    print('  git commit -m "Import blog post"')
    print(f"  git push origin {branch}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
