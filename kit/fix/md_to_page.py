"""Render a schema-change page (markdown in a fix worktree) as an Artifact-ready HTML page.

  python md_to_page.py <slug> <md path in repo> "<Title, 2-4 words>" <out.html>

Relative links become absolute GitHub links on the branch, tables and code scroll in their own box, light and dark.
YAML front matter is dropped; a star (U+2605) marks the recommended option and renders as a "recommended" chip.
Needs `pip install markdown`. You wrote the generator, but read the markdown in full before publishing what it renders.
"""
import html, json, os, posixpath, re, sys
import markdown

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = json.load(open(os.path.join(HERE, "loop.json"), encoding="utf8"))
slug, rel, title, out = sys.argv[1:5]
wt = os.path.join(CONF["WT_ROOT"], slug)
src = open(os.path.join(wt, rel), encoding="utf-8").read()
src = re.sub(r"\A---\r?\n.*?\r?\n---\r?\n", "", src, count=1, flags=re.S)  # drop YAML front matter
branch = f"{CONF['BRANCH_PREFIX']}{CONF.get('SLUG_PREFIX', '')}{slug}"
base_dir = posixpath.dirname(rel)


def absolutise(m):
    text, href = m.group(1), m.group(2)
    if re.match(r"^(https?:|mailto:|#)", href):
        return m.group(0)
    path, _, frag = href.partition("#")
    resolved = posixpath.normpath(posixpath.join(base_dir, path))
    url = f"https://github.com/{CONF['GH_REPO']}/blob/{branch}/{resolved}" + (f"#{frag}" if frag else "")
    return f"[{text}]({url})"


src = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", absolutise, src)
body = markdown.markdown(src, extensions=["tables", "fenced_code", "sane_lists"])
body = re.sub(r"<table>", '<div class="tw"><table>', body).replace("</table>", "</table></div>")
body = body.replace("<pre>", '<pre class="code">')
body = body.replace("★", '<span class="rec">recommended</span>')
body = re.sub(r'<a href="(https?://[^"]+)"', r'<a href="\1" target="_blank" rel="noopener"', body)

page = f"""<title>{html.escape(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap">
<style>
:root{{
  --bg:#f7f8fa; --card:#ffffff; --ink:#0f1729; --ink-2:#475467; --muted:#667085; --line:#e4e7ec; --divider:#eef0f3;
  --code-bg:#f2f4f7; --link:#2563eb; --head-bg:#f5f6f8;
  --rec-fg:#067647; --rec-bg:#ecfdf3; --rec-bd:#d1fae5;
  --flag-fg:#b54708; --flag-bg:#fffaeb; --flag-bd:#fef3c7;
  --ui:"Inter",system-ui,-apple-system,"Segoe UI",sans-serif;
  --mono:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,monospace;
}}
@media (prefers-color-scheme: dark){{
  :root:not([data-theme="light"]){{
    color-scheme:dark;
    --bg:#0f131b; --card:#161b26; --ink:#e8ecf3; --ink-2:#b4bccb; --muted:#8f99ab; --line:#2a3242; --divider:#222938;
    --code-bg:#1b2130; --link:#7aa2ff; --head-bg:#1b2130;
    --rec-fg:#5fd49a; --rec-bg:#12291f; --rec-bd:#1d3f2f;
    --flag-fg:#f3b364; --flag-bg:#2a2114; --flag-bd:#44341b;
  }}
}}
:root[data-theme="dark"]{{
  color-scheme:dark;
  --bg:#0f131b; --card:#161b26; --ink:#e8ecf3; --ink-2:#b4bccb; --muted:#8f99ab; --line:#2a3242; --divider:#222938;
  --code-bg:#1b2130; --link:#7aa2ff; --head-bg:#1b2130;
  --rec-fg:#5fd49a; --rec-bg:#12291f; --rec-bd:#1d3f2f;
  --flag-fg:#f3b364; --flag-bg:#2a2114; --flag-bd:#44341b;
}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font-family:var(--ui);font-size:14.5px;line-height:1.6;-webkit-font-smoothing:antialiased}}
.wrap{{max-width:980px;margin:0 auto;padding-inline:24px;padding-block:32px 96px}}
@media (max-width:600px){{.wrap{{padding-inline:16px}}}}
.kind{{display:inline-flex;gap:8px;align-items:center;font-size:11.5px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;color:var(--flag-fg);background:var(--flag-bg);border:1px solid var(--flag-bd);border-radius:999px;padding:3px 10px}}
h1{{font-size:26px;line-height:1.25;font-weight:700;letter-spacing:-.02em;margin:12px 0 10px;text-wrap:balance}}
h1 code{{font-size:.8em}}
h2{{font-size:19px;font-weight:700;letter-spacing:-.01em;margin:40px 0 10px;padding-top:18px;border-top:1px solid var(--line);text-wrap:balance}}
h3{{font-size:15.5px;font-weight:700;margin:26px 0 8px}}
p,li{{color:var(--ink-2);max-width:78ch}}
p strong,li strong,td strong{{color:var(--ink)}}
ul,ol{{padding-left:22px}} li{{margin:4px 0}}
a{{color:var(--link);text-decoration:none;overflow-wrap:anywhere}} a:hover{{text-decoration:underline}}
code{{font-family:var(--mono);font-size:12.5px;background:var(--code-bg);border:1px solid var(--divider);border-radius:4px;padding:0 4px;overflow-wrap:anywhere}}
pre.code{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;overflow-x:auto;font-size:12.5px;line-height:1.55}}
pre.code code{{background:none;border:0;padding:0;overflow-wrap:normal;white-space:pre}}
.tw{{overflow-x:auto;border:1px solid var(--line);border-radius:10px;background:var(--card);margin:12px 0}}
table{{border-collapse:collapse;width:100%;font-size:13.5px;min-width:620px}}
th{{text-align:left;font-size:11.5px;font-weight:600;letter-spacing:.03em;color:var(--muted);background:var(--head-bg);border-bottom:1px solid var(--divider);padding:8px 12px}}
td{{padding:9px 12px;border-bottom:1px solid var(--divider);color:var(--ink-2);vertical-align:top}}
tr:last-child td{{border-bottom:0}}
td:first-child{{color:var(--ink);font-weight:500}}
.rec{{display:inline-block;font-size:11px;font-weight:600;color:var(--rec-fg);background:var(--rec-bg);border:1px solid var(--rec-bd);border-radius:999px;padding:0 8px;margin-left:4px;vertical-align:1px}}
@media (max-width:600px){{h1{{font-size:22px}}}}
</style>

<div class="wrap">
<span class="kind">Schema change · proposed · awaiting sign-off ({html.escape(CONF.get("OWNER", "the owner"))})</span>
{body}
</div>
"""
os.makedirs(os.path.dirname(out), exist_ok=True)
open(out, "w", encoding="utf-8").write(page)
print("wrote", out, len(page), "bytes")
