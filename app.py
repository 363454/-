import os
import threading
import time
import urllib.parse
import urllib.request

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

IDX_URL = os.environ.get("IDX_URL", "https://363454.github.io/-/idx.txt")
SITE = "https://www.shuhaoxs.com"
PAGE_SIZE = 100

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


@app.get("/health")
def health():
    return {"ok": True, "rows": len(_state["lines"])}
