#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AmorWiki v2 — Wikipedia-style web app for the Greek books wiki.

Features:
  * Browse books, authors, tags; full-text search; random article; A-Z bar.
  * Wikipedia-like article pages with an infobox (metadata) and wiki-links.
  * CRUD: create, edit, delete books (write the underlying .md files).
  * Recycle bin: deleted books move to amorwiki/trash/ instead of hard delete.
  * Optional edit password (config.json -> "password").
  * LAN access (binds 0.0.0.0) so phones on the same Wi-Fi can use it.
  * Mobile-responsive layout.

Run:  python amorwiki_server.py
"""
import http.server
import os
import re
import sys
import json
import time
import socket
import shutil
import hashlib
import urllib.parse
from pathlib import Path

try:
    from markdown import markdown
except Exception:
    print("Απαιτείται το πακέτο 'markdown'. Εγκατάσταση: pip install markdown")
    sys.exit(1)

# Root resolution:
#   Cloud mode (PORT env set, e.g. Render/Railway): always use this script's folder.
#   Local mode: use the Google-Drive wiki if present, else this script's folder.
_IS_CLOUD = bool(os.environ.get("PORT"))
if _IS_CLOUD:
    ROOT = Path(__file__).resolve().parent
else:
    _LOCAL_WIKI = Path(r"G:\Το Drive μου\Βιβλία που διάβασα\wiki")
    if _LOCAL_WIKI.exists():
        ROOT = _LOCAL_WIKI.resolve()
    else:
        ROOT = Path(__file__).resolve().parent
BOOKS = ROOT / "books"
APP_DIR = ROOT / "amorwiki"
TRASH = APP_DIR / "trash"
JOURNAL = APP_DIR / "journal.json"
CONFIG_PATH = APP_DIR / "config.json"

DEFAULT_PORT = 8765

def load_config():
    cfg = {"port": DEFAULT_PORT, "password": ""}
    try:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, encoding="utf-8") as f:
                cfg.update(json.load(f))
    except Exception:
        pass
    return cfg

CONFIG = load_config()
# Cloud platforms (Render/Railway/Fly) set PORT via env var; local uses config.json
PORT = int(os.environ.get("PORT", CONFIG.get("port", DEFAULT_PORT)))
EDIT_PASSWORD = str(os.environ.get("AMORWIKI_PASSWORD", "") or CONFIG.get("password", "") or "")

TRASH.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# CSS (Wikipedia-flavoured, light, responsive)
# ---------------------------------------------------------------------------
CSS = """
:root{
  --bg:#fff;--ink:#202122;--muted:#54595d;--line:#c8ccd1;--accent:#36c;--accent-d:#2a4b8d;
  --bg2:#f8f9fa;--bg3:#eaf3ff;--sidebar:#f6f6f6;--infobox:#f8f9fa;--ok:#14866d;--danger:#d33;
}
*{box-sizing:border-box} html,body{margin:0;padding:0;height:100%}
body{font:15px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,"Noto Sans",Helvetica,Arial,sans-serif;color:var(--ink);background:var(--bg);display:flex;flex-direction:column;min-height:100vh}
a{color:var(--accent);text-decoration:none} a:hover{text-decoration:underline}
img{max-width:100%}

/* Header */
header{position:sticky;top:0;z-index:50;background:#fff;border-bottom:1px solid var(--line);
  display:flex;align-items:center;gap:.7rem;padding:.45rem .9rem;flex-wrap:wrap}
.logo{display:flex;align-items:center;gap:.5rem;font-weight:700;font-size:19px;color:var(--ink);text-decoration:none}
.logo:hover{text-decoration:none}
.logo .badge{background:var(--accent);color:#fff;border-radius:6px;padding:.1rem .4rem;font-size:13px}
.searchbox{flex:1 1 200px;display:flex;gap:.3rem;max-width:640px}
.searchbox input{flex:1;padding:.42rem .65rem;border:1px solid var(--line);border-radius:8px 0 0 8px;font:inherit;outline:none}
.searchbox input:focus{border-color:var(--accent)}
.searchbox button{padding:.42rem .8rem;border:1px solid var(--line);border-left:none;border-radius:0 8px 8px 0;background:var(--bg2);cursor:pointer;font:inherit}
.hdr-links{display:flex;gap:.7rem;align-items:center;font-size:14px;margin-left:auto}

/* Layout */
.layout{display:flex;flex:1}
aside{width:190px;flex:0 0 190px;background:var(--sidebar);border-right:1px solid var(--line);padding:1rem .9rem;font-size:14px}
aside h4{margin:.4rem 0 .35rem;font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.03em}
aside ul{list-style:none;margin:0 0 .9rem;padding:0}
aside li{margin:.22rem 0}
aside a{color:var(--ink)} aside a:hover{color:var(--accent);text-decoration:none}
main{flex:1;padding:1.2rem 1.6rem;min-width:0;max-width:1100px}
main article{max-width:820px}

/* Mobile: sidebar becomes a top strip */
@media (max-width:760px){
  .layout{flex-direction:column}
  aside{width:100%;flex:none;border-right:none;border-bottom:1px solid var(--line);
    display:flex;flex-wrap:wrap;gap:.3rem .8rem;padding:.5rem .8rem;font-size:13px}
  aside h4{display:none}
  aside ul{display:flex;flex-wrap:wrap;gap:.2rem .9rem;margin:0}
  aside li{margin:0}
  main{padding:1rem}
  .hdr-links span.extra{display:none}
}

h1{font-size:26px;border-bottom:1px solid var(--line);padding-bottom:.25rem;margin:.1rem 0 .8rem}
h2{font-size:20px;border-bottom:1px solid var(--line);padding-bottom:.15rem;margin:1.1rem 0 .4rem}
h3{font-size:17px;margin:1rem 0 .3rem}
article blockquote{margin:.8rem 0;padding:.6rem 1rem;border-left:4px solid var(--line);background:var(--bg2);color:#3a3c3f}
article ul,article ol{padding-left:1.5rem}
article table{border-collapse:collapse;width:100%;margin:.6rem 0}
article th,article td{border:1px solid var(--line);padding:.4rem .55rem;text-align:left}
article hr{border:none;border-top:1px solid var(--line)}

/* Infobox (Wikipedia-style) */
.infobox{float:right;width:290px;background:var(--infobox);border:1px solid var(--line);
  border-radius:8px;margin:0 0 1rem 1.2rem;font-size:13px}
.infobox .ib-title{background:var(--bg3);border-bottom:1px solid var(--line);padding:.5rem .7rem;font-weight:700;font-size:14px;text-align:center}
.infobox table{width:100%;border-collapse:collapse}
.infobox th{width:38%;text-align:left;vertical-align:top;color:var(--muted);padding:.4rem .6rem;font-weight:600;border-bottom:1px solid #eaecf0}
.infobox td{vertical-align:top;padding:.4rem .6rem;border-bottom:1px solid #eaecf0}
@media (max-width:760px){.infobox{float:none;width:100%;margin:0 0 1rem}}

.tags{display:flex;flex-wrap:wrap;gap:.35rem;margin:.5rem 0}
.tags a{background:var(--bg3);color:var(--accent-d);border:1px solid #bcd4f6;border-radius:999px;
  padding:.1rem .6rem;font-size:12.5px}
.tags a:hover{text-decoration:none;background:#dbe9fb}

/* Action buttons */
.actions{display:flex;gap:.5rem;margin:.4rem 0 1rem;flex-wrap:wrap}
.btn{display:inline-block;padding:.4rem .8rem;border:1px solid var(--line);border-radius:8px;
  background:var(--bg2);color:var(--ink);font:inherit;font-size:14px;cursor:pointer;text-decoration:none}
.btn:hover{background:#eef;text-decoration:none}
.btn.primary{background:var(--accent);border-color:var(--accent);color:#fff}
.btn.primary:hover{background:var(--accent-d)}
.btn.danger{color:var(--danger);border-color:#f5c6c6;background:#fff7f7}
.btn.danger:hover{background:#fdecec}
.btn.mini{padding:.1rem .45rem;border-radius:6px;font-size:13px;line-height:1.4;display:inline-block;vertical-align:middle}
.rowbtns{float:right;display:inline-flex;gap:.25rem;align-items:center}
@media (max-width:760px){.rowbtns{float:none;margin-left:.4rem}}

/* Filters */
.filters{display:flex;gap:.5rem;flex-wrap:wrap;margin:.6rem 0 .8rem}
.filters input[type=text]{flex:1 1 180px;padding:.42rem .6rem;border:1px solid var(--line);border-radius:8px;font:inherit}
.filters select{padding:.42rem .5rem;border:1px solid var(--line);border-radius:8px;background:#fff;font:inherit}
.ac-wrap{position:relative;flex:1 1 160px}
.ac-wrap input{width:100%;padding:.42rem .6rem;border:1px solid var(--line);border-radius:8px;font:inherit;background:#fff}
.ac-list{display:none;position:absolute;top:100%;left:0;right:0;background:#fff;border:1px solid var(--line);border-radius:8px;
  max-height:280px;overflow:auto;z-index:60;box-shadow:0 4px 14px rgba(0,0,0,.14)}
.ac-item{padding:.42rem .6rem;cursor:pointer;font-size:13.5px;border-bottom:1px solid #f0f0f0}
.ac-item:hover{background:var(--bg3)}
.az{display:flex;flex-wrap:wrap;gap:.3rem;margin:.4rem 0 .8rem}
.az a{padding:.15rem .55rem;border:1px solid var(--line);border-radius:6px;font-size:13px;background:#fff;color:var(--ink)}
.az a:hover{background:var(--bg3);text-decoration:none}
.az a.on{background:var(--accent);color:#fff;border-color:var(--accent)}

.count{color:var(--muted);font-size:13px;margin-bottom:.4rem}
.book-row{padding:.5rem 0;border-bottom:1px solid var(--line)}
.book-row a.book-title{font-size:16px;font-weight:600;color:var(--ink)}
.book-row a.book-title:hover{color:var(--accent)}
.book-row .meta{color:var(--muted);font-size:13px}

/* Stats */
.stats{background:var(--bg2);border:1px solid var(--line);border-radius:10px;padding:1rem;margin:0 0 1.2rem}
.stats .tiles{display:flex;gap:.8rem;flex-wrap:wrap}
.stats .tile{background:#fff;border:1px solid var(--line);border-radius:8px;padding:.45rem .8rem;min-width:100px;text-align:center;text-decoration:none;color:var(--ink);display:block}
.stats .tile:hover{border-color:var(--accent);background:var(--bg3);text-decoration:none}
.stats .tile b{display:block;font-size:20px}
.stats .tile span{font-size:11px;color:var(--muted)}

/* Forms */
.form-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:.7rem;margin-bottom:1rem}
.form-grid label{display:block;font-size:13px;color:var(--muted);margin-bottom:.2rem}
.form-grid input,.form-grid select,.form-grid textarea{padding:.45rem .6rem;border:1px solid var(--line);border-radius:8px;font:inherit;width:100%;background:#fff}
textarea#body{width:100%;min-height:300px;font-family:ui-monospace,Consolas,"Courier New",monospace;font-size:13.5px;line-height:1.55;padding:.6rem;border:1px solid var(--line);border-radius:8px}
.form-full{grid-column:1/-1}
.form-actions{display:flex;gap:.6rem;margin-top:.6rem;flex-wrap:wrap}

.notice{border:1px solid #d1e7dd;background:#f0faf5;color:#0f5132;border-radius:8px;padding:.6rem .9rem;margin-bottom:1rem}
.error{border:1px solid #f5c6c6;background:#fff5f5;color:#842029;border-radius:8px;padding:.6rem .9rem;margin-bottom:1rem}

/* Journal / tables */
.journal td{padding:.4rem .6rem;border-bottom:1px solid var(--line)}
.journal td.ts{color:var(--muted);white-space:nowrap;font-size:13px}

footer{border-top:1px solid var(--line);padding:.8rem 1rem;color:var(--muted);font-size:12.5px;text-align:center}
@media print{.no-print{display:none!important} aside{display:none!important} .infobox{float:none;width:100%}}
"""

# ---------------------------------------------------------------------------
# Markdown helpers
# ---------------------------------------------------------------------------
def clean_link(v):
    return re.sub(r"^\[\[(.*)\]\]$", r"\1", v.strip())

def parse_frontmatter(text):
    out = {}
    m = re.match(r"^---\s*\r?\n([\s\S]*?)\r?\n---", text)
    if not m:
        return out
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    if "author" in out:
        out["author"] = clean_link(out["author"])
    if "title" in out:
        out["title"] = clean_link(out["title"])
    return out

def body_of(text):
    return re.sub(r"^---[\s\S]*?---\s*", "", text).strip()

def fmt_author(v):
    """Return (display, link_name).  If author is an Obsidian link [[X]] -> link."""
    v = v.strip()
    m = re.match(r"^\[\[(.+?)\]\]$", v)
    if m:
        return m.group(1), m.group(1)
    return v, v

def split_tags(tags):
    if not tags:
        return []
    t = re.sub(r"[\[\]\"']", "", tags)
    return [x.strip() for x in t.split(",") if x.strip()]

def title_to_slug_map():
    m = {}
    for p in BOOKS.glob("*.md"):
        fm = parse_frontmatter(p.read_text(encoding="utf-8", errors="ignore"))
        t = fm.get("title", p.stem)
        m[t.lower()] = p.name
        m[p.stem.lower()] = p.name
    return m

def slugify(title):
    """Turn a book title into a filesystem-safe slug (keep Greek letters)."""
    s = title.strip().replace("/", "-").replace("\\", "-")
    s = re.sub(r"[:\*\?\"<>|]+", "", s)
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "biblio"

# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
_CACHE = {"mtime": 0.0, "rows": None}

def collect_books():
    rows = []
    for p in sorted(BOOKS.glob("*.md")):
        txt = p.read_text(encoding="utf-8", errors="ignore")
        fm = parse_frontmatter(txt)
        rows.append({
            "title": fm.get("title", p.stem),
            "slug": p.name,
            "author": fm.get("author", ""),
            "year": fm.get("read_year", ""),
            "publisher": fm.get("publisher", ""),
            "status": fm.get("status", ""),
            "rating": fm.get("rating", ""),
            "tags": fm.get("tags", ""),
        })
    rows.sort(key=lambda x: x["title"].lower())
    return rows

def cached_books(force=False):
    if force:
        _CACHE["rows"] = None
    try:
        latest = max(p.stat().st_mtime for p in BOOKS.glob("*.md"))
    except Exception:
        latest = 0.0
    if _CACHE["rows"] is None or latest != _CACHE["mtime"]:
        _CACHE["rows"] = collect_books()
        _CACHE["mtime"] = latest
    return _CACHE["rows"]

def invalidate_cache():
    """Force the book list to be re-read from disk on the next request.
    Called after create/save/delete so edits and deletions show immediately."""
    _CACHE["rows"] = None

def find_book_by_slug(slug):
    for p in BOOKS.glob("*.md"):
        if p.name.lower() == slug.lower():
            return p
    return None

def find_book_by_title(title):
    for p in BOOKS.glob("*.md"):
        fm = parse_frontmatter(p.read_text(encoding="utf-8", errors="ignore"))
        if fm.get("title", "").strip().lower() == title.strip().lower():
            return p
    return None

# ---------------------------------------------------------------------------
# Wiki-links
# ---------------------------------------------------------------------------
def resolve_wikilinks(body_html):
    t2s = title_to_slug_map()
    def repl(m):
        label = m.group(1).strip()
        target = label
        if "|" in label:
            target, label = label.split("|", 1)
            target, label = target.strip(), label.strip()
        # author links like [[Τζον-Στέφανσον]] should go to author page if not a book
        slug = t2s.get(target.lower())
        if slug:
            href = "/amorwiki/books/" + urllib.parse.quote(slug)
            return '<a href="' + href + '">' + label + "</a>"
        # else try author page
        href = "/amorwiki/authors/" + urllib.parse.quote(target)
        return '<a href="' + href + '">' + label + "</a>"
    return re.sub(r"\[\[([^\[\]]+)\]\]", repl, body_html)

def render_markdown(text):
    body = re.sub(r"^---[\s\S]*?---\s*", "", text).strip()
    body = re.sub(r"\r\n?", "\n", body)
    html = markdown(body, extensions=["extra", "nl2br"])
    return resolve_wikilinks(html)

# ---------------------------------------------------------------------------
# Page shell
# ---------------------------------------------------------------------------
def shell(title, content, active=""):
    def li(path, label):
        cls = ' class="on"' if active == label else ""
        return '<li%s><a href="%s">%s</a></li>' % (cls, path, label)

    sidebar = (
        "<aside><h4>Πλοήγηση</h4><ul>"
        + li("/amorwiki/home", "Κεντρική")
        + li("/amorwiki/books", "Βιβλία")
        + li("/amorwiki/authors", "Συγγραφείς")
        + li("/amorwiki/tags", "Ετικέτες")
        + li("/amorwiki/recent", "Πρόσφατες αλλαγές")
        + li("/amorwiki/help", "Βοήθεια")
        + "</ul><h4>Εργαλεία</h4><ul>"
        + li("/amorwiki/new", "Προσθήκη βιβλίου")
        + "</ul></aside>"
    )

    hdr = (
        '<header class="no-print">'
        '<a class="logo" href="/amorwiki/home"><span class="badge">Α</span>ΑμορWiki</a>'
        '<form class="searchbox" action="/amorwiki/search" method="get">'
        '<input type="text" name="q" placeholder="Αναζήτηση στο wiki…" value="">'
        '<button type="submit">🔍</button></form>'
        '<div class="hdr-links">'
        '<a href="/amorwiki/home">Κεντρική</a>'
        '<span class="extra">·</span><a class="extra" href="/amorwiki/new">+ Προσθήκη</a>'
        '</div></header>'
    )

    html = (
        '<!doctype html><html lang="el"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>' + title + ' — ΑμορWiki</title><style>' + CSS + "</style></head><body>"
        + hdr
        + '<div class="layout">' + sidebar + "<main>" + content + "</main></div>"
        + '<footer class="no-print">ΑμορWiki — Βιβλία που διάβασα · '
        + str(len(cached_books())) + " βιβλία</footer>"
        + "</body></html>"
    )
    return html

def esc(s):
    if s is None:
        return ""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def meta_field(fm, key, label):
    v = fm.get(key, "")
    if not v or v == "—":
        return ""
    return "<tr><th>" + label + "</th><td>" + esc(v) + "</td></tr>"

def build_infobox(fm):
    rows = ""
    rows += meta_field(fm, "author", "Συγγραφέας")
    rows += meta_field(fm, "publisher", "Εκδότης")
    rows += meta_field(fm, "read_year", "Χρονιά ανάγνωσης")
    rows += meta_field(fm, "meeting_date", "Ημερομηνία")
    rows += meta_field(fm, "rating", "Βαθμολογία")
    rows += meta_field(fm, "status", "Κατάσταση")
    tags = split_tags(fm.get("tags", ""))
    if tags:
        tag_links = " ".join('<a href="/amorwiki/tags/' + urllib.parse.quote(t) + '">' + esc(t) + "</a>" for t in tags)
        rows += "<tr><th>Ετικέτες</th><td>" + tag_links + "</td></tr>"
    if not rows:
        return ""
    return '<div class="infobox"><div class="ib-title">Πληροφορίες βιβλίου</div><table>' + rows + "</table></div>"

# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
def book_row_html(r, show_author=True, show_edit=False):
    """A single book row in list pages. No inline edit/delete buttons —
    those live only at the bottom of the book's own page."""
    meta = [x for x in [r.get("author") if show_author else "", r.get("year"), r.get("publisher"), r.get("status")] if x]
    return (
        '<div class="book-row">'
        '<a class="book-title" href="/amorwiki/books/' + urllib.parse.quote(r["slug"]) + '">' + esc(r["title"]) + "</a>"
        + '<div class="meta">' + " · ".join(meta) + "</div></div>"
    )

def list_rows(rows, show_author=True):
    return "".join(book_row_html(r, show_author=show_author) for r in rows)

def page_home():
    rows = cached_books()
    years = sorted({r["year"] for r in rows if r["year"]})
    tags = sorted({t.strip() for r in rows for t in split_tags(r["tags"])})

    total = len(rows)
    na = len({r["author"] for r in rows if r["author"]})
    npub = len({r["publisher"] for r in rows if r["publisher"]})

    def tile(n, label, href):
        return (
            '<a class="tile" href="' + href + '">'
            "<b>" + str(n) + "</b><span>" + label + "</span></a>"
        )

    stats = (
        '<div class="stats"><div class="tiles">'
        + tile(total, "Βιβλία", "/amorwiki/books")
        + tile(na, "Συγγραφείς", "/amorwiki/authors")
        + tile(npub, "Εκδότες", "/amorwiki/publishers")
        + tile(len(tags), "Ετικέτες", "/amorwiki/tags")
        + "</div></div>"
    )

    # enrich rows with tags_list for client-side filtering
    rows2 = []
    for r in rows:
        rr = dict(r)
        rr["tags_list"] = split_tags(r["tags"])
        rows2.append(rr)

    year_opts = '<option value="">Έτος (όλα)</option>'
    for y in years:
        year_opts += '<option value="' + esc(y) + '">' + esc(y) + "</option>"

    ac_fields = (
        '<div class="ac-wrap"><input id="fQ" type="text" placeholder="Αναζήτηση τίτλου…" autocomplete="off">'
        '<div class="ac-list" id="acQ"></div></div>'
        '<div class="ac-wrap"><input id="fA" type="text" placeholder="Συγγραφέας…" autocomplete="off">'
        '<div class="ac-list" id="acA"></div></div>'
        '<div class="ac-wrap"><input id="fP" type="text" placeholder="Εκδότης…" autocomplete="off">'
        '<div class="ac-list" id="acP"></div></div>'
        '<div class="ac-wrap"><input id="fT" type="text" placeholder="Ετικέτα…" autocomplete="off">'
        '<div class="ac-list" id="acT"></div></div>'
        '<select id="fY">' + year_opts + "</select>"
    )

    script = (
        '<script id="data" type="application/json">' + json.dumps(rows2, ensure_ascii=False) + "</script>"
        "<script>"
        "(function(){"
        "var data=JSON.parse(document.getElementById('data').textContent);"
        "var list=document.getElementById('list'),count=document.getElementById('count');"
        "var fQ=document.getElementById('fQ'),fA=document.getElementById('fA');"
        "var fP=document.getElementById('fP'),fT=document.getElementById('fT'),fY=document.getElementById('fY');"
        "function uni(key){var s=new Set();data.forEach(function(r){if(r[key])s.add(r[key]);});"
        "return Array.from(s).sort(function(a,b){return a.localeCompare(b,'el');});}"
        "var titles=uni('title'),authors=uni('author'),pubs=uni('publisher');"
        "var tagSet=new Set();data.forEach(function(r){(r.tags_list||[]).forEach(function(t){if(t)tagSet.add(t);});});"
        "var tags=Array.from(tagSet).sort(function(a,b){return a.localeCompare(b,'el');});"
        "function esc(s){return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}"
        "function render(){"
        "var q=fQ.value.trim().toLowerCase(),a=fA.value.trim().toLowerCase();"
        "var p=fP.value.trim().toLowerCase(),t=fT.value.trim().toLowerCase(),y=fY.value;"
        "var res=data.filter(function(r){"
        "if(q&&(r.title||'').toLowerCase().indexOf(q)!==0)return false;"
        "if(a&&(r.author||'').toLowerCase().indexOf(a)!==0)return false;"
        "if(p&&(r.publisher||'').toLowerCase().indexOf(p)!==0)return false;"
        "if(t){var hit=(r.tags_list||[]).some(function(x){return x.toLowerCase().indexOf(t)===0;});if(!hit)return false;}"
        "if(y&&r.year!==y)return false;"
        "return true;});"
        "count.textContent=res.length+' βιβλία';"
        "list.innerHTML=res.map(function(r){"
        "return '<div class=\"book-row\">'"
        "+'<a class=\"book-title\" href=\"/amorwiki/books/'+encodeURIComponent(r.slug)+'\">'+esc(r.title)+'</a>'"
        "+'<div class=\"meta\">'+[r.author,r.year,r.publisher,r.status].filter(Boolean).join(' · ')+'</div>'"
        "+'</div>';}).join('');"
        "}"
        "function ac(inp,box,vals){"
        "function show(){var v=inp.value.trim().toLowerCase();"
        "var m=v?vals.filter(function(x){return x.toLowerCase().indexOf(v)===0;}).slice(0,15):vals.slice(0,15);"
        "box.innerHTML=m.map(function(x){return '<div class=\"ac-item\">'+esc(x)+'</div>';}).join('');"
        "box.style.display=m.length?'block':'none';}"
        "inp.addEventListener('input',function(){show();render();});"
        "inp.addEventListener('focus',show);"
        "box.addEventListener('mousedown',function(e){e.preventDefault();var it=e.target.closest('.ac-item');"
        "if(it){inp.value=it.textContent;box.style.display='none';render();}});"
        "inp.addEventListener('keydown',function(e){if(e.key==='Enter'){e.preventDefault();var it=box.querySelector('.ac-item');"
        "if(it){inp.value=it.textContent;box.style.display='none';render();}}});"
        "document.addEventListener('click',function(e){if(!e.target.closest('.ac-wrap'))box.style.display='none';});"
        "}"
        "ac(fQ,document.getElementById('acQ'),titles);"
        "ac(fA,document.getElementById('acA'),authors);"
        "ac(fP,document.getElementById('acP'),pubs);"
        "ac(fT,document.getElementById('acT'),tags);"
        "fY.addEventListener('change',render);"
        "render();"
        "})();"
        "</script>"
    )

    content = (
        "<h1>Κατάλογος βιβλίων</h1>"
        + stats
        + '<div class="filters">' + ac_fields + "</div>"
        + '<div class="count" id="count"></div>'
        + '<div id="list"></div>'
        + script
    )
    return shell("ΑμορWiki", content, "Κεντρική")

def book_actions_html(p, title):
    """EDIT / DELETE / Raw / PDF action buttons for a book page."""
    return (
        '<div class="actions no-print">'
        '<a class="btn primary" href="/amorwiki/edit/' + urllib.parse.quote(p.name) + '">✏️ Επεξεργασία</a>'
        '<form method="post" action="/amorwiki/delete" onsubmit="return confirm(\'Σίγουρα να διαγραφεί το «' + esc(title).replace("'", "\\'") + '»;\\nΘα πάει στον κάδο (trash).\');">'
        '<input type="hidden" name="slug" value="' + esc(p.name) + '">'
        '<button class="btn danger" type="submit">🗑 Διαγραφή</button></form>'
        '<a class="btn" href="/amorwiki/raw/' + urllib.parse.quote(p.name) + '">Raw MD</a>'
        '<a class="btn" href="#" onclick="window.print();return false;">🖨 PDF</a>'
        "</div>"
    )

def page_book(slug):
    p = find_book_by_slug(slug)
    if not p:
        return None
    txt = p.read_text(encoding="utf-8", errors="ignore")
    fm = parse_frontmatter(txt)
    title = fm.get("title", p.stem)
    body_html = render_markdown(txt)
    infobox = build_infobox(fm)

    tags = split_tags(fm.get("tags", ""))
    tag_html = ""
    if tags:
        tag_html = '<div class="tags">' + "".join(
            '<a href="/amorwiki/tags/' + urllib.parse.quote(t) + '">#' + esc(t) + "</a>" for t in tags
        ) + "</div>"

    actions = book_actions_html(p, title)

    # Prev/next
    rows = cached_books()
    titles = [r["title"] for r in rows]
    idx = -1
    for i, t in enumerate(titles):
        if t.lower() == title.lower():
            idx = i
            break
    prev = titles[idx - 1] if idx > 0 else None
    nxt = titles[idx + 1] if 0 <= idx < len(titles) - 1 else None
    t2s = title_to_slug_map()
    pn = ""
    if prev or nxt:
        cells = ""
        if prev:
            cells += '<a href="/amorwiki/books/' + urllib.parse.quote(t2s.get(prev.lower(), prev)) + '">← ' + esc(prev) + "</a>"
        else:
            cells += "<span></span>"
        if nxt:
            cells += '<a href="/amorwiki/books/' + urllib.parse.quote(t2s.get(nxt.lower(), nxt)) + '">' + esc(nxt) + " →</a>"
        else:
            cells += "<span></span>"
        pn = '<div class="actions" style="justify-content:space-between;border-top:1px solid var(--line);padding-top:.6rem;margin-top:1rem">' + cells + "</div>"

    content = (
        "<h1>" + esc(title) + "</h1>"
        + infobox
        + "<article>" + body_html + "</article>"
        + tag_html
        + actions
        + pn
    )
    return shell(title + " — ΑμορWiki", content)

def page_raw(slug):
    p = find_book_by_slug(slug)
    if not p:
        return None
    return p.read_text(encoding="utf-8", errors="ignore")

def page_not_found():
    """Friendly 'not found!' page shown when a book was deleted or doesn't exist."""
    content = (
        "<h1>not found!</h1>"
        "<p>Το βιβλίο αυτό δεν βρέθηκε. Μπορεί να διαγράφηκε ή η διεύθυνση να είναι λάθος.</p>"
        '<p><a class="btn" href="/amorwiki/home">← Επιστροφή στην Κεντρική</a></p>'
    )
    return shell("not found! — ΑμορWiki", content)

def page_authors():
    rows = cached_books()
    by_auth = {}
    for r in rows:
        a = r["author"]
        if not a:
            continue
        by_auth.setdefault(a, []).append(r)
    items = "".join(
        '<div class="book-row"><a class="book-title" href="/amorwiki/authors/' + urllib.parse.quote(a) + '">' + esc(a) + "</a>"
        '<div class="meta">' + str(len(lst)) + " βιβλία</div></div>"
        for a, lst in sorted(by_auth.items(), key=lambda x: x[0].lower())
    )
    content = "<h1>Συγγραφείς</h1><div class='count'>" + str(len(by_auth)) + " συγγραφείς</div>" + items
    return shell("Συγγραφείς — ΑμορWiki", content, "Συγγραφείς")

def page_author(name):
    rows = cached_books()
    mine = [r for r in rows if r["author"].lower() == name.lower()]
    if not mine:
        return shell(name + " — ΑμορWiki", "<h1>" + esc(name) + "</h1><p>Δεν βρέθηκαν βιβλία.</p>", "Συγγραφείς")
    content = "<h1>" + esc(name) + "</h1><div class='count'>" + str(len(mine)) + " βιβλία</div>" + list_rows(mine, show_author=False)
    return shell(name + " — ΑμορWiki", content, "Συγγραφείς")

def page_tags():
    rows = cached_books()
    by_tag = {}
    for r in rows:
        for t in split_tags(r["tags"]):
            by_tag.setdefault(t, 0)
            by_tag[t] += 1
    items = "".join(
        '<div class="book-row"><a class="book-title" href="/amorwiki/tags/' + urllib.parse.quote(t) + '">#' + esc(t) + "</a>"
        '<div class="meta">' + str(c) + " βιβλία</div></div>"
        for t, c in sorted(by_tag.items(), key=lambda x: (-x[1], x[0]))
    )
    content = "<h1>Ετικέτες</h1><div class='count'>" + str(len(by_tag)) + " ετικέτες</div>" + items
    return shell("Ετικέτες — ΑμορWiki", content, "Ετικέτες")

def page_books():
    """All books, alphabetical, with edit/delete buttons. Linked from the 'Βιβλία' menu."""
    rows = cached_books()
    content = "<h1>Βιβλία</h1><div class='count'>" + str(len(rows)) + " βιβλία</div>" + list_rows(rows)
    return shell("Βιβλία — ΑμορWiki", content, "Βιβλία")

def page_publishers():
    """Publishers with book counts; clicking one lists that publisher's books."""
    rows = cached_books()
    by_pub = {}
    for r in rows:
        p = r.get("publisher", "")
        if not p:
            continue
        by_pub.setdefault(p, 0)
        by_pub[p] += 1
    items = "".join(
        '<div class="book-row"><a class="book-title" href="/amorwiki/publishers/' + urllib.parse.quote(p) + '">' + esc(p) + "</a>"
        '<div class="meta">' + str(c) + " βιβλία</div></div>"
        for p, c in sorted(by_pub.items(), key=lambda x: (-x[1], x[0].lower()))
    )
    content = "<h1>Εκδότες</h1><div class='count'>" + str(len(by_pub)) + " εκδότες</div>" + items
    return shell("Εκδότες — ΑμορWiki", content)

def page_publisher(name):
    rows = cached_books()
    mine = [r for r in rows if (r.get("publisher") or "").lower() == name.lower()]
    if not mine:
        return shell(name + " — ΑμορWiki", "<h1>" + esc(name) + "</h1><p>Δεν βρέθηκαν βιβλία.</p>")
    content = "<h1>" + esc(name) + "</h1><div class='count'>" + str(len(mine)) + " βιβλία</div>" + list_rows(mine)
    return shell(name + " — ΑμορWiki", content)

def page_tag(tag):
    rows = cached_books()
    mine = [r for r in rows if tag in split_tags(r["tags"])]
    content = "<h1>#" + esc(tag) + "</h1><div class='count'>" + str(len(mine)) + " βιβλία</div>" + list_rows(mine)
    return shell("#" + tag + " — ΑμορWiki", content)

def page_search(q):
    rows = cached_books()
    q = q.strip()
    if not q:
        return page_home()
    ql = q.lower()
    results = []
    for r in rows:
        hay = (r["title"] + " " + r["author"] + " " + r["tags"]).lower()
        if ql in hay:
            results.append(r)
    # also search body
    if not results:
        for p in BOOKS.glob("*.md"):
            txt = p.read_text(encoding="utf-8", errors="ignore")
            if ql in txt.lower():
                fm = parse_frontmatter(txt)
                results.append({
                    "title": fm.get("title", p.stem), "slug": p.name,
                    "author": fm.get("author", ""), "year": fm.get("read_year", ""),
                    "publisher": fm.get("publisher", ""), "status": fm.get("status", ""),
                    "tags": fm.get("tags", ""),
                })
    content = "<h1>Αποτελέσματα για: " + esc(q) + "</h1><div class='count'>" + str(len(results)) + " αποτελέσματα</div>" + (list_rows(results) or "<p class='muted'>Δεν βρέθηκε τίποτα.</p>")
    return shell("Αναζήτηση: " + q + " — ΑμορWiki", content)

def page_random():
    rows = cached_books()
    if not rows:
        return None
    import random
    r = random.choice(rows)
    return ("/amorwiki/books/" + urllib.parse.quote(r["slug"]))

def page_recent():
    entries = []
    try:
        if JOURNAL.exists():
            with open(JOURNAL, encoding="utf-8") as f:
                entries = json.load(f)
    except Exception:
        entries = []
    entries = entries[-60:][::-1]
    if not entries:
        content = "<h1>Πρόσφατες αλλαγές</h1><p>Δεν υπάρχουν καταγραφές ακόμα.</p>"
    else:
        rows = "".join(
            "<tr><td class='ts'>" + esc(e.get("ts", "")) + "</td><td>" + esc(e.get("action", ""))
            + ' — <a href="/amorwiki/books/' + urllib.parse.quote(e.get("slug", "")) + '">' + esc(e.get("title", "")) + "</a></td></tr>"
            for e in entries
        )
        content = "<h1>Πρόσφατες αλλαγές</h1><table class='journal'>" + rows + "</table>"
    return shell("Πρόσφατες αλλαγές — ΑμορWiki", content, "Πρόσφατες αλλαγές")

def page_help():
    content = (
        "<h1>Βοήθεια — ΑμορWiki</h1>"
        "<p>Η ΑμορWiki είναι η προσωπική σας βιβλιοθήκη σε μορφή Wikipedia. "
        "Όλα τα δεδομένα αποθηκεύονται ως αρχεία Markdown στον φάκελο "
        "<code>G:\\Το Drive μου\\Βιβλία που διάβασα\\wiki\\books\\</code> — "
        "συγχρονίζονται αυτόματα με το Google Drive.</p>"
        "<h2>Πλοήγηση</h2><ul>"
        "<li><b>Κεντρική</b> — κατάλογος όλων των βιβλίων με αναζήτηση, φίλτρα (συγγραφέας/έτος/εκδότης/ετικέτα) και Α-Ω μπάρα.</li>"
        "<li><b>Συγγραφείς</b> — κάθε συγγραφέας έχει τη δική του σελίδα με τα βιβλία του.</li>"
        "<li><b>Ετικέτες</b> — κάθε ετικέτα ομαδοποιεί τα σχετικά βιβλία.</li>"
        "<li><b>Τυχαίο βιβλίο</b> — ανακάλυψη.</li>"
        "<li><b>Πρόσφατες αλλαγές</b> — ιστορικό προσθηκών/επεξεργασιών/διαγραφών.</li>"
        "</ul>"
        "<h2>Επεξεργασία</h2><ul>"
        "<li><b>✏️ Επεξεργασία</b> — σε κάθε σελίδα βιβλίου ανοίγει φόρμα με όλα τα πεδία (τίτλος, συγγραφέας, εκδότης, έτος, βαθμολογία, κατάσταση, ετικέτες) + το Markdown περιεχόμενο.</li>"
        "<li><b>➕ Προσθήκη βιβλίου</b> — από το μενού «Εργαλεία» αριστερά.</li>"
        "<li><b>🗑 Διαγραφή</b> — το βιβλίο μετακινείται στον κάδο <code>amorwiki\\trash\\</code> (δεν χάνεται οριστικά).</li>"
        "</ul>"
        "<h2>Πρόσβαση από κινητό</h2><p>Στο ίδιο Wi-Fi με τον υπολογιστή, ανοίξτε στο κινητό τη διεύθυνση "
        "<b>http://192.168.1.7:8765/amorwiki/home</b>. "
        "Αν δεν ανοίγει, τρέξτε μία φορά το <code>Άνοιγμα θύρας για κινητό.bat</code> ως διαχειριστής.</p>"
        "<h2>Πρόσβαση από το διαδίκτυο</h2><p>Τρέξτε το <code>Άνοιγμα από Internet.bat</code> — δημιουργεί "
        "προσωρινή δημόσια διεύθυνση https://...trycloudflare.com για να μπαίνετε από οπουδήποτε. "
        "Κλείστε το παράθυρο όταν τελειώσετε.</p>"
        "<h2>Ασφάλεια επεξεργασίας</h2><p>Αν θέλετε να μπορούν να επεξεργάζονται βιβλία μόνο όσοι ξέρουν κωδικό, "
        "ανοίξτε το <code>amorwiki\\config.json</code> και βάλτε το πεδίο <code>\"password\": \"Ο-κωδικός-σας\"</code>. "
        "Ο server θα ζητάει τον κωδικό πριν από κάθε αλλαγή.</p>"
    )
    return shell("Βοήθεια — ΑμορWiki", content, "Βοήθεια")

# ---------------------------------------------------------------------------
# Auth (optional password)
# ---------------------------------------------------------------------------
def auth_cookie_ok(cookie):
    if not EDIT_PASSWORD:
        return True
    if not cookie:
        return False
    expected = hashlib.sha256(EDIT_PASSWORD.encode("utf-8")).hexdigest()
    return cookie == expected

def auth_page(redirect=""):
    return shell(
        "Κωδικός — ΑμορWiki",
        "<h1>Προστασία επεξεργασίας</h1>"
        "<p>Για να επεξεργαστείτε ή να διαγράψετε βιβλία, εισάγετε τον κωδικό.</p>"
        '<form method="post" action="/amorwiki/login">'
        '<input type="hidden" name="redirect" value="' + esc(redirect) + '">'
        '<div class="form-grid"><div class="form-full"><label>Κωδικός</label>'
        '<input type="password" name="pw"></div></div>'
        '<div class="form-actions"><button class="btn primary" type="submit">Είσοδος</button></div>'
        "</form>"
    )

def check_auth(self, redirect):
    if not EDIT_PASSWORD:
        return None, True
    cookies = self.headers.get("Cookie", "")
    ok = False
    for c in cookies.split(";"):
        c = c.strip()
        if c.startswith("amorwiki_auth="):
            ok = auth_cookie_ok(c[len("amorwiki_auth="):])
    if not ok:
        return auth_page(redirect), False
    return None, True

def read_post(self):
    length = int(self.headers.get("Content-Length", 0) or 0)
    body = self.rfile.read(length).decode("utf-8", errors="replace") if length else ""
    return dict(urllib.parse.parse_qsl(body))

def journal_add(action, title, slug):
    entries = []
    try:
        if JOURNAL.exists():
            with open(JOURNAL, encoding="utf-8") as f:
                entries = json.load(f)
    except Exception:
        entries = []
    entries.append({"ts": time.strftime("%Y-%m-%d %H:%M"), "action": action, "title": title, "slug": slug})
    try:
        with open(JOURNAL, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False)
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Write helpers (build .md files)
# ---------------------------------------------------------------------------
def today():
    return time.strftime("%Y-%m-%d")

def build_md(fields, body, existing=None):
    """Rebuild the markdown file preserving a sensible frontmatter order."""
    keys = ["title", "author", "created", "read_year", "updated", "type", "subtype",
            "tags", "publisher", "meeting_date", "rating", "status", "sources"]
    lines = ["---"]
    seen = set()
    # Preserve existing unknown fields first
    if existing:
        e = parse_frontmatter(existing)
        for k in e:
            if k not in keys and k not in fields:
                lines.append(k + ": " + e[k])
                seen.add(k)
    for k in keys:
        v = fields.get(k)
        if v is None or v == "":
            if existing:
                e = parse_frontmatter(existing)
                if k in e and k != "updated":
                    lines.append(k + ": " + e[k])
            continue
        if k == "updated":
            v = today()
        if k == "tags":
            if isinstance(v, list):
                v = "[" + ", ".join(v) + "]"
            else:
                v = v.strip()
                if v and not v.startswith("["):
                    v = "[" + v + "]"
        if k == "author" and v and not v.startswith("[["):
            v = "[[" + v + "]]"
        lines.append(k + ": " + v)
        seen.add(k)
    lines.append("---")
    body = (body or "").strip()
    md = "\r\n".join(lines) + "\r\n\r\n" + body + "\r\n"
    return md

def save_book(slug, fields, body):
    p = find_book_by_slug(slug)
    if not p:
        return None
    existing = p.read_text(encoding="utf-8", errors="ignore")
    fields["updated"] = today()
    md = build_md(fields, body, existing)
    p.write_text(md, encoding="utf-8")
    journal_add("Επεξεργασία", fields.get("title", p.stem), p.name)
    invalidate_cache()
    return p.name

def create_book(fields, body):
    title = (fields.get("title") or "").strip()
    if not title:
        return None, "Δώστε τίτλο"
    if find_book_by_title(title):
        return None, "Υπάρχει ήδη βιβλίο με αυτόν τον τίτλο"
    slug = slugify(title)
    p = BOOKS / (slug + ".md")
    if p.exists():
        p = BOOKS / (slug + "-" + time.strftime("%Y%m%d%H%M%S") + ".md")
    md = build_md(fields, body, None)
    p.write_text(md, encoding="utf-8")
    journal_add("Προσθήκη", title, p.name)
    invalidate_cache()
    return p.name, None

def delete_book(slug):
    p = find_book_by_slug(slug)
    if not p:
        return None, "Δεν βρέθηκε"
    dest = TRASH / (time.strftime("%Y%m%d-%H%M%S") + "-" + p.name)
    shutil.move(str(p), str(dest))
    journal_add("Διαγραφή", p.stem, "")
    invalidate_cache()
    return dest.name, None

# ---------------------------------------------------------------------------
# Edit / New form
# ---------------------------------------------------------------------------
def edit_form(slug, err=""):
    p = find_book_by_slug(slug)
    if not p:
        return None
    txt = p.read_text(encoding="utf-8", errors="ignore")
    fm = parse_frontmatter(txt)
    body = body_of(txt)
    title = fm.get("title", p.stem)
    author = clean_link(fm.get("author", ""))
    return form_page(title, fm, body, p.name, err, is_new=False)

def new_form(err=""):
    fm = {"title": "", "author": "", "publisher": "", "read_year": "", "meeting_date": "",
          "rating": "—", "status": "διαβασμένο", "tags": "", "sources": "[Books.xlsx]"}
    return form_page("Νέο βιβλίο", fm, "", "", err, is_new=True)

def form_page(page_title, fm, body, slug, err, is_new):
    action = "/amorwiki/create" if is_new else "/amorwiki/save"
    hid = "" if is_new else '<input type="hidden" name="slug" value="' + esc(slug) + '">'
    err_html = '<div class="error">' + esc(err) + "</div>" if err else ""
    content = (
        "<h1>" + ("Προσθήκη νέου βιβλίου" if is_new else "Επεξεργασία: " + esc(fm.get("title", ""))) + "</h1>"
        + err_html
        + '<form method="post" action="' + action + '">' + hid
        + '<div class="form-grid">'
        + field("title", "Τίτλος *", fm.get("title", ""))
        + field("author", "Συγγραφέας", fm.get("author", ""))
        + field("publisher", "Εκδότης", fm.get("publisher", ""))
        + field("read_year", "Χρονιά ανάγνωσης", fm.get("read_year", ""))
        + field("meeting_date", "Ημερομηνία", fm.get("meeting_date", ""))
        + field("rating", "Βαθμολογία", fm.get("rating", ""))
        + field("status", "Κατάσταση", fm.get("status", ""))
        + field("tags", "Ετικέτες (κόμμα διαχωρισμένες)", fm.get("tags", ""))
        + "</div>"
        + '<div class="form-grid"><div class="form-full"><label for="body">Περιεχόμενο (Markdown)</label>'
        + '<textarea id="body" name="body">' + esc(body) + "</textarea></div></div>"
        + '<div class="form-actions">'
        + '<button class="btn primary" type="submit">' + ("➕ Δημιουργία" if is_new else "💾 Αποθήκευση") + "</button>"
        + '<a class="btn" href="' + (("/amorwiki/books/" + urllib.parse.quote(slug)) if not is_new else "/amorwiki/home") + '">Ακύρωση</a>'
        + "</div></form>"
    )
    return shell(page_title + " — ΑμορWiki", content)

def field(name, label, value):
    return (
        '<div><label for="' + name + '">' + label + '</label>'
        '<input id="' + name + '" name="' + name + '" value="' + esc(value) + '"></div>'
    )

# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------
class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("[amorwiki] " + (fmt % args) + "\n")

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _redirect(self, location):
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        raw = urllib.parse.unquote(parsed.path)
        q = urllib.parse.parse_qs(parsed.query)
        # Public health endpoint for the uptime monitor.
        if raw in ("/amorwiki/ping", "/ping"):
            self._send(200, b"pong", "text/plain; charset=utf-8")
            return
        if raw in ("/", "/amorwiki", "/amorwiki/"):
            self._redirect("/amorwiki/home")
            return
        if not raw.startswith("/amorwiki/"):
            self._redirect("/amorwiki/home")
            return

        route = raw[len("/amorwiki/"):]
        parts = [x for x in route.split("/") if x]

        try:
            if not parts or parts[0] == "home":
                self._send(200, page_home().encode("utf-8"))
            elif parts[0] == "books" and len(parts) == 2:
                html = page_book(parts[1])
                if html is None:
                    self._send(404, page_not_found().encode("utf-8"))
                else:
                    self._send(200, html.encode("utf-8"))
            elif parts[0] == "books":
                self._send(200, page_books().encode("utf-8"))
            elif parts[0] == "raw" and len(parts) == 2:
                rawtxt = page_raw(parts[1])
                if rawtxt is None:
                    self._send(404, b"404")
                else:
                    self._send(200, rawtxt.encode("utf-8"), "text/plain; charset=utf-8")
            elif parts[0] == "authors" and len(parts) == 2:
                self._send(200, page_author(parts[1]).encode("utf-8"))
            elif parts[0] == "authors":
                self._send(200, page_authors().encode("utf-8"))
            elif parts[0] == "publishers" and len(parts) == 2:
                self._send(200, page_publisher(parts[1]).encode("utf-8"))
            elif parts[0] == "publishers":
                self._send(200, page_publishers().encode("utf-8"))
            elif parts[0] == "tags" and len(parts) == 2:
                self._send(200, page_tag(parts[1]).encode("utf-8"))
            elif parts[0] == "tags":
                self._send(200, page_tags().encode("utf-8"))
            elif parts[0] == "search":
                self._send(200, page_search(q.get("q", [""])[0]).encode("utf-8"))
            elif parts[0] == "random":
                loc = page_random()
                self._redirect(loc if loc else "/amorwiki/home")
            elif parts[0] == "recent":
                self._send(200, page_recent().encode("utf-8"))
            elif parts[0] == "help":
                self._send(200, page_help().encode("utf-8"))
            elif parts[0] == "edit" and len(parts) == 2:
                guard, ok = check_auth(self, "/amorwiki/edit/" + parts[1])
                if not ok:
                    self._send(200, guard.encode("utf-8"))
                else:
                    html = edit_form(parts[1])
                    if html is None:
                        self._send(404, b"404")
                    else:
                        self._send(200, html.encode("utf-8"))
            elif parts[0] == "new":
                guard, ok = check_auth(self, "/amorwiki/new")
                if not ok:
                    self._send(200, guard.encode("utf-8"))
                else:
                    self._send(200, new_form().encode("utf-8"))
            else:
                self._send(404, b"404")
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._send(500, ("Σφάλμα: " + str(e)).encode("utf-8"))

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        route = urllib.parse.unquote(parsed.path)
        if not route.startswith("/amorwiki/"):
            self._redirect("/amorwiki/home")
            return
        action = route[len("/amorwiki/"):].split("/")[0]
        data = read_post(self)

        # Login
        if action == "login":
            pw = data.get("pw", "")
            if auth_cookie_ok(hashlib.sha256(pw.encode("utf-8")).hexdigest()):
                redir = data.get("redirect", "/amorwiki/home")
                self.send_response(302)
                self.send_header("Location", redir if redir.startswith("/") else "/amorwiki/home")
                self.send_header("Set-Cookie", "amorwiki_auth=" + hashlib.sha256(pw.encode("utf-8")).hexdigest()
                                 + "; Path=/; Max-Age=86400")
                self.end_headers()
            else:
                self._send(200, auth_page("/amorwiki/home").replace("<h1>Κωδικός</h1>",
                             '<div class="error">Λάθος κωδικός</div><h1>Κωδικός</h1>').encode("utf-8"))
            return

        # Guard all write actions
        guard, ok = check_auth(self, "/amorwiki/home")
        if not ok:
            self._send(200, guard.encode("utf-8"))
            return

        try:
            if action == "save":
                slug = data.get("slug", "")
                fields = {k: data.get(k, "") for k in
                          ["title", "author", "publisher", "read_year", "meeting_date", "rating", "status", "tags"]}
                body = data.get("body", "")
                if not fields.get("title", "").strip():
                    self._send(200, edit_form(slug, "Δώστε τίτλο").encode("utf-8"))
                    return
                saved = save_book(slug, fields, body)
                self._redirect("/amorwiki/books/" + urllib.parse.quote(saved))
            elif action == "create":
                fields = {k: data.get(k, "") for k in
                          ["title", "author", "publisher", "read_year", "meeting_date", "rating", "status", "tags"]}
                fields["created"] = today()
                fields["updated"] = today()
                fields.setdefault("type", "entity")
                fields.setdefault("subtype", "book")
                body = data.get("body", "")
                slug, err = create_book(fields, body)
                if err:
                    self._send(200, new_form(err).encode("utf-8"))
                else:
                    self._redirect("/amorwiki/books/" + urllib.parse.quote(slug))
            elif action == "delete":
                slug = data.get("slug", "")
                dest, err = delete_book(slug)
                if err:
                    self._send(200, ("<div class='error'>" + esc(err) + "</div>").encode("utf-8"))
                else:
                    self._redirect("/amorwiki/home")
            else:
                self._redirect("/amorwiki/home")
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._send(500, ("Σφάλμα: " + str(e)).encode("utf-8"))

# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------
def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def main():
    global PORT
    # pick an available port if the configured one is taken
    for _ in range(5):
        try:
            server = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
            break
        except OSError:
            PORT += 1
    else:
        print("Δεν βρέθηκε διαθέσιμη θύρα")
        sys.exit(1)

    ip = lan_ip()
    is_cloud = bool(os.environ.get("PORT"))
    print("=" * 58)
    print("  ΑμορWiki v2 — Wikipedia-style βιβλιοθήκη")
    print("=" * 58)
    if is_cloud:
        print("  Λειτουργία cloud:  http://0.0.0.0:%d/amorwiki/home" % PORT)
    else:
        print("  Σε αυτόν τον υπολογιστή:  http://127.0.0.1:%d/amorwiki/home" % PORT)
        print("  Κινητό (ίδιο Wi-Fi):      http://%s:%d/amorwiki/home" % (ip, PORT))
    if EDIT_PASSWORD:
        print("  Προστασία επεξεργασίας:   ΕΝΕΡΓΗ (κωδικός απαιτείται για αλλαγές)")
    else:
        print("  Προστασία επεξεργασίας:   ΑΠΕΝΕΡΓΗ — ο καθένας μπορεί να επεξεργαστεί")
    print("=" * 58)
    print("  Πατήστε Ctrl+C για διακοπή.")
    if not is_cloud:
        import threading, webbrowser, time
        t = threading.Thread(target=lambda: (time.sleep(0.5), webbrowser.open("http://127.0.0.1:%d/amorwiki/home" % PORT)), daemon=True)
        t.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nΤερματισμός.")
        server.server_close()

if __name__ == "__main__":
    main()
