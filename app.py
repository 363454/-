import html as htmlmod
import os
import re
import threading
import time
import urllib.parse
import urllib.request

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

IDX_URL = os.environ.get("IDX_URL", "https://363454.github.io/-/idx.txt")
SITE = "https://www.shuhaoxs.com"
PAGE_SIZE = 100
UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
)

_state = {"lines": [], "ts": 0.0}
_lock = threading.Lock()


def load_index():
    with _lock:
        if _state["lines"] and (time.time() - _state["ts"] < 3600):
            return _state["lines"]
        try:
            req = urllib.request.Request(IDX_URL, headers={"User-Agent": "Mozilla/5.0"})
            body = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
            rows = [line for line in body.split("\n") if line]
            if rows:
                _state["lines"] = rows
                _state["ts"] = time.time()
        except Exception:
            pass
        return _state["lines"]


def esc(text):
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def fetch(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": SITE + "/",
        },
    )
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")


PROMO = re.compile(
    r"(shuhaoxs\.com|书豪小说网|分类导航|立即阅读正文|开启今日精彩|读取当前章节内容失败"
    r"|yimozww\.com|bingrenxs\.com|tongnianshuwu\.com|baimaxsw\.com|请退出|本章未完|点击下一页)"
)


def content_text(page):
    m = re.search(r'<div class="content"[^>]*>(.*?)</div>', page, re.S)
    if not m:
        return ""
    body = m.group(1).replace("</p>", "\n")
    body = re.sub(r"<[^>]+>", "", body)
    body = htmlmod.unescape(body)
    lines = []
    for raw in body.split("\n"):
        line = raw.replace("\u00a0", " ").strip()
        if not line:
            continue
        if PROMO.search(line):
            continue
        if line in ("下一页", "上一页"):
            continue
        lines.append(line)
    return "\n".join(lines)


app = FastAPI()


@app.get("/")
@app.get("/search")
def search(kw: str = "", p: int = 1, fmt: str = ""):
    raw = (kw or "").strip()
    toks = [t for t in raw.replace("\u3000", " ").split(" ") if t]
    rows = load_index()

    hits = []
    if toks and rows:
        head, mid = [], []
        for line in rows:
            parts = line.split("|")
            if len(parts) < 2:
                continue
            title = parts[1]
            author = parts[2] if len(parts) > 2 else ""
            hay = title + " " + author
            ok = True
            for t in toks:
                if t not in hay:
                    ok = False
                    break
            if not ok:
                continue
            item = (parts[0], title, author)
            if title.startswith(toks[0]):
                head.append(item)
            else:
                mid.append(item)
        hits = head + mid

    total = len(hits)
    max_page = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(1, p)
    chunk = hits[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]

    if fmt.lower() == "json":
        return JSONResponse({
            "success": True,
            "total": total,
            "maxPage": max_page,
            "list": [
                {
                    "bookName": t,
                    "author": a,
                    "detailUrl": SITE + "/book/" + aid + ".html",
                }
                for (aid, t, a) in chunk
            ],
        })

    buf = [
        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">',
        "<title>" + esc(raw or "搜索") + "</title></head><body>",
        '<div id="hd">' + esc(raw) + " 共 " + str(total) + " 本 第 " + str(page) + "/" + str(max_page) + " 页</div>",
    ]
    for (aid, title, author) in chunk:
        buf.append(
            '<div class="bc"><a href="' + SITE + "/book/" + aid + '.html"><h3>'
            + esc(title) + "</h3></a><span>" + esc(author) + "</span></div>"
        )
    buf.append("</body></html>")
    return HTMLResponse("".join(buf))


@app.get("/read")
def read(u: str = ""):
    target = (u or "").strip()
    if not target.startswith("http"):
        target = SITE + (target if target.startswith("/") else "/" + target)
    if "shuhaoxs.com" not in target:
        return PlainTextResponse("bad url", status_code=400)

    chunks = []
    for idx, page_url in enumerate([target, target.replace(".html", "-2.html")]):
        if idx == 1:
            if not page_url.endswith("-2.html"):
                break
        try:
            page = fetch(page_url)
        except Exception:
            break
        text = content_text(page)
        if not text:
            continue
        if len(text) < 120 and "读取" in text:
            continue
        chunks.append(text)
        if idx == 1:
            break

    body = "\n".join(chunks).strip()
    if not body:
        body = "本章内容暂时无法读取（站点本身缺失该章正文）。"
    return HTMLResponse(
        '<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>'
        '<div class="content"><p>' + esc(body).replace("\n", "</p><p>") + "</p></div>"
        "</body></html>"
    )


@app.get("/dbg")
def dbg(u: str = ""):
    try:
        page = fetch(u)
    except Exception as exc:
        return PlainTextResponse("ERR " + type(exc).__name__ + " " + str(exc)[:200], status_code=500)
    idx = page.find('class="content"')
    head = page[:300]
    seg = page[max(0, idx - 60): idx + 500] if idx > 0 else "NO_CONTENT_DIV"
    return PlainTextResponse("HEAD>>> " + head + "\n\n=== CONTENT AREA ===\n" + seg)


@app.get("/health")
def health():
    return {"ok": True, "rows": len(_state["lines"])}
