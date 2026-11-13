"""Bring a chain-written design page in line with the Artifact page contract before publishing: no skeleton of its own
(the host wraps it), and a side gutter of at least 16px at phone width. Prints what it changed.

  python fix_page.py <page.html>

It doesn't replace reading the page: read it in full before publishing (the Artifact tool requires it), check the title is
a 2-4 word name, the dark-mode tokens exist, and that no other published page says the same thing on the same screen.
"""
import re, sys

p = sys.argv[1]
s = open(p, encoding="utf-8", newline="").read()
done = []
for pat in [r"<!doctype html>\s*", r"<html[^>]*>\s*", r"<head>\s*", r"<meta charset=[^>]*>\s*", r"<meta name=\"viewport\"[^>]*>\s*",
            r"</head>\s*", r"<body[^>]*>\s*", r"\s*</body>", r"\s*</html>"]:
    s, n = re.subn(pat, "\n" if pat.startswith(r"\s*") else "", s, count=1, flags=re.I)
    if n:
        done.append(pat.replace(r"\s*", ""))


def fix_gutter(m):
    rule = m.group(0)
    new = re.sub(r"padding-inline:(\d+)px", lambda k: f"padding-inline:{max(16, int(k.group(1)))}px", rule)
    new = re.sub(r"padding:(\d+)px (\d+)px( \d+px)?\}", lambda k: f"padding:{k.group(1)}px {max(16, int(k.group(2)))}px{k.group(3) or ''}}}", new)
    return new


s2 = re.sub(r"\.wrap\{[^}]*\}", fix_gutter, s)
if s2 != s:
    done.append("gutter>=16px"); s = s2
s = s.lstrip()
open(p, "w", encoding="utf-8", newline="").write(s)
print("fixed:", ", ".join(done) or "nothing")
print("starts:", s[:70].replace("\n", " "))
title = re.search(r"<title>(.*?)</title>", s[:8000])
print("title:", title.group(1) if title else "MISSING (must be in the first 8 KB)")
print("dark tokens:", "ok" if 'prefers-color-scheme: dark' in s and '[data-theme="dark"]' in s else "MISSING")
