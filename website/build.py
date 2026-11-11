"""Builds website/public/*.html from website/pages/*.html (each page = its <main> content; the first line is
`<!-- title | description -->`). Adds the shared header and footer.  python -m website.build"""
from __future__ import annotations

import html
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent

HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{desc}">
<meta name="referrer" content="same-origin">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:image" content="/img/editor.webp">
<link rel="icon" href="/img/icon.svg" type="image/svg+xml">
<link rel="stylesheet" href="/css/site.css">
<script src="/js/site.js" defer></script>
</head>
<body data-page="{page}">
<header class="nav"><div class="wrap">
  <a class="brand" href="/"><span class="logo">&#9654;</span>AnKar Video Editor</a>
  <nav>
    <a href="/start">Get started</a>
    <a href="/whatsnew">What's new</a>
    <a href="#" data-github class="hidden">GitHub</a>
    <a href="/signin" id="navAcct" class="btn small primary">Sign in</a>
  </nav>
</div></header>
<div class="wrap"><div id="flash" class="msg hidden" role="status"></div></div>
"""
FOOT = """
<footer><div class="wrap">
  <span>AnKar Video Editor · free &amp; open source (MIT)</span><span class="sp"></span>
  <a href="/privacy">Privacy</a><a href="/terms">Terms</a><a href="/whatsnew">What's new</a><a href="#" data-github class="hidden">Source code</a>
</div></footer>
</body>
</html>
"""


def main():
    out = HERE / "public"
    for src in sorted((HERE / "pages").glob("*.html")):
        text = src.read_text(encoding="utf-8")
        m = re.match(r"<!--\s*(.*?)\s*\|\s*(.*?)\s*-->\n", text)
        if not m:
            raise SystemExit(f"{src.name}: first line must be <!-- title | description -->")
        page = src.stem
        title = m.group(1) if page == "index" else f"{m.group(1)} · AnKar Video Editor"
        body = text[m.end():]
        (out / src.name).write_text(HEAD.format(title=html.escape(title), desc=html.escape(m.group(2)),
                                                page="home" if page == "index" else page) + body + FOOT, encoding="utf-8")
        print("built", src.name)


if __name__ == "__main__":
    main()
