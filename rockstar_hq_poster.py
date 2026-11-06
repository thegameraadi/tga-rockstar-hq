#!/usr/bin/env python3
"""
Rockstar HQ poster for the TGA x GTA VI Discord server.

What it does (every 15 minutes when run by GitHub Actions):
  1. Reads Rockstar Games' YouTube feed and posts new GTA VI videos.
  2. Reads Rockstar's official GTA VI pages (home, media, music, Only in Leonida,
     newswire tag, Rockstar Store collection) and posts anything NEW:
       - a newswire article  -> embed with Rockstar's own summary, image and link
       - a new GTA VI site page, store item, or artwork/screenshot/trailer image
  3. If Rockstar's site cannot be reached at all, falls back to a Google News RSS
     search limited to rockstargames.com, so the channel never goes silent.

It posts through a Discord webhook (no bot token, no hosting), remembers what it
has posted in state.json, and never posts the same thing twice. Standard library
only: no pip install.

Usage:
  DISCORD_WEBHOOK_URL=... python3 rockstar_hq_poster.py            # normal run
  python3 rockstar_hq_poster.py --dry-run                           # print, post nothing
  python3 rockstar_hq_poster.py --test-webhook                      # one test message
  python3 rockstar_hq_poster.py --backfill 3                        # first run: also post newest 3 per source

Environment (all optional except the webhook):
  DISCORD_WEBHOOK_URL   webhook of #rockstar-hq (required to post)
  PING_ROLE_ID          role id to ping for newswire posts (leave empty for no pings)
  YT_CHANNEL_ID         override the Rockstar Games channel id
  YT_FILTER             "0" posts every Rockstar upload, default only GTA VI ones
  SITE_PAGES            "0" turns off the website watcher (YouTube only)
  STATE_FILE            default state.json
  GEMINI_API_KEY        optional; adds a 3-bullet AI TL;DR under each newswire post (free Google AI Studio key)
  GEMINI_MODEL          default gemini-2.5-flash (change it if Google retires the name)
"""
import argparse
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

# ----------------------------------------------------------------- config --
YT_CHANNEL_ID = os.environ.get("YT_CHANNEL_ID", "UC6VcWc1rAoWdBCM0JxrRQ3A")  # Rockstar Games
YT_FEED = "https://www.youtube.com/feeds/videos.xml?channel_id={}"
YT_ONLY_GTA6 = os.environ.get("YT_FILTER", "1") != "0"
GTA6_PATTERN = re.compile(r"grand theft auto vi\b|gta ?vi\b|gta ?6\b|leonida|vice city", re.I)

SITE = "https://www.rockstargames.com"
STORE = "https://store.rockstargames.com"
WATCH_PAGES = [
    f"{SITE}/VI",
    f"{SITE}/VI/media",
    f"{SITE}/VI/music",
    f"{SITE}/VI/only-in-leonida",
    f"{SITE}/newswire?tag=vi",
    f"{STORE}/grand-theft-auto-vi-collection",
]
GOOGLE_NEWS = ("https://news.google.com/rss/search?q="
               + urllib.parse.quote('"Grand Theft Auto VI" site:rockstargames.com')
               + "&hl=en-US&gl=US&ceid=US:en")

USER_AGENT = "Mozilla/5.0 (compatible; TGA-RockstarHQ/1.0; +https://thegameraadi.com)"
BRAND_COLOR = 0x7C3AED
FOOTER = "Source: Rockstar Games. Mirrored by TGA x GTA VI (unofficial fan server)."
MAX_SITE_POSTS_PER_RUN = 6
ALERT_AFTER_FAILURES = 8  # consecutive failing runs (about 2 hours) before the Action fails loudly once

STATE_FILE = os.environ.get("STATE_FILE", "state.json")
RECENT_FILE = os.environ.get("RECENT_FILE", "recent.json")   # last 20 posted items, read by the TGA Bot's /whatsnew
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "").strip()      # optional: adds an AI TL;DR under each newswire post
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "").strip() or "gemini-2.5-flash"
WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
PING_ROLE_ID = os.environ.get("PING_ROLE_ID", "").strip()

NEWS_RE = re.compile(r"/newswire/article/([a-z0-9]{10,18})", re.I)
VI_PAGE_RE = re.compile(r"""["'(\s]/VI/([a-z0-9][a-z0-9\-]*(?:/[a-z0-9\-]+)*)["')\s?#]""", re.I)
MEDIA_RE = re.compile(r"""(?:https?://www\.rockstargames\.com)?(/VI/_next/static/media/([A-Za-z0-9_~\-]+)\.[A-Za-z0-9_~\-.]*?\.(?:jpg|jpeg|png|webp))""", re.I)
STORE_RE = re.compile(r"""href=["']((?:https://store\.rockstargames\.com)?/(?:products?|collections?)/[^"'#?]*(?:grand-theft-auto-vi|gta-vi|gtavi)[^"'#?]*)["']""", re.I)

DRY = False
NO_PING = False  # no role pings while backfilling on the first run


# ------------------------------------------------------------------ http ---
def http_get(url, accept="*/*"):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept,
                                               "Accept-Language": "en-US,en;q=0.9"})
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (403, 404, 410):
                break  # retrying will not help, and we do not try to dodge a block
        except Exception as e:  # network hiccup
            last = e
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"GET {url} failed: {last}")


def http_post_json(url, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": USER_AGENT})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status
        except urllib.error.HTTPError as e:
            if e.code == 429:
                try:
                    wait = float(json.loads(e.read().decode()).get("retry_after", 2))
                except Exception:
                    wait = 2
                time.sleep(wait + 0.5)
                continue
            raise RuntimeError(f"Discord webhook error {e.code}: {e.read().decode(errors='replace')[:300]}")
    raise RuntimeError("Discord webhook rate limit did not clear")


def record_recent(payload):
    """Remember the last 20 posted items (title, link, time) in recent.json for the TGA Bot's /whatsnew."""
    emb = (payload.get("embeds") or [{}])[0]
    title = (emb.get("title") or "").strip()
    url = (emb.get("url") or "").strip()
    if not url:
        m = re.search(r"https?://[^\s<>]+", payload.get("content", ""))
        url = m.group(0) if m else ""
    if not title:
        title = re.sub(r"<@&\d+>|https?://\S+", "", payload.get("content", "")).strip()[:140]
    if not (title or url):
        return
    try:
        with open(RECENT_FILE, encoding="utf-8") as f:
            items = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        items = []
    items.insert(0, {"t": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "title": title[:200], "url": url})
    with open(RECENT_FILE, "w", encoding="utf-8") as f:
        json.dump(items[:20], f, indent=1, ensure_ascii=False)


def post(payload):
    """Send one message to #rockstar-hq. Returns True if it was posted (or dry-run)."""
    payload = dict(payload)
    norecent = payload.pop("_norecent", False)
    payload.setdefault("username", "Rockstar HQ")
    payload["allowed_mentions"] = {"parse": []}
    if payload.pop("_ping", False) and PING_ROLE_ID and not NO_PING:
        payload["content"] = f"<@&{PING_ROLE_ID}> " + payload.get("content", "")
        payload["allowed_mentions"] = {"roles": [PING_ROLE_ID]}
    if DRY:
        print("DRY-RUN POST:", json.dumps(payload, ensure_ascii=False)[:900])
        return True
    if not WEBHOOK:
        raise RuntimeError("DISCORD_WEBHOOK_URL is not set")
    http_post_json(WEBHOOK, payload)
    try:
        if not norecent:
            record_recent(payload)
    except Exception as e:  # never let bookkeeping stop a post
        print("recent.json not updated:", e)
    time.sleep(1.2)  # stay well under Discord's webhook rate limit
    return True


# ----------------------------------------------------------------- state ---
def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            s = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        s = {}
    s.setdefault("seeded", False)
    s.setdefault("youtube", [])
    s.setdefault("site", [])
    s.setdefault("gnews", [])
    s.setdefault("fail", {"youtube": 0, "site": 0})
    return s


def save_state(s):
    s["youtube"] = s["youtube"][-300:]
    s["site"] = s["site"][-1500:]
    s["gnews"] = s["gnews"][-200:]
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=1, ensure_ascii=False)


# --------------------------------------------------------------- parsing ---
class MetaParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta = {}
        self.title = ""
        self._in_title = False
        self.ld = []
        self._in_ld = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key and "content" in a and key not in self.meta:
                self.meta[key] = a["content"]
        elif tag == "title":
            self._in_title = True
        elif tag == "script" and a.get("type") == "application/ld+json":
            self._in_ld = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "script":
            self._in_ld = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif self._in_ld:
            self.ld.append(data)


def clean_title(t):
    t = html.unescape(t or "").strip()
    return re.sub(r"\s*[-|]\s*Rockstar Games\s*$", "", t)


def trim(text, n):
    text = html.unescape(re.sub(r"\s+", " ", text or "")).strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def parse_article(page_html, url):
    p = MetaParser()
    try:
        p.feed(page_html)
    except Exception:
        pass
    m = p.meta
    title = clean_title(m.get("og:title") or p.title)
    desc = m.get("og:description") or m.get("description") or ""
    image = m.get("og:image") or m.get("twitter:image") or ""
    published = m.get("article:published_time") or ""
    if not published:
        for blob in p.ld:
            mm = re.search(r'"datePublished"\s*:\s*"([^"]+)"', blob)
            if mm:
                published = mm.group(1)
                break
    # Rockstar tags its newswire links with utm_campaign=...-YYYYMMDD; use it as a date hint
    if not published:
        mm = re.search(r"utm_campaign=[a-z0-9_\-]*?-(20\d{6})", page_html)
        if mm:
            d = mm.group(1)
            published = f"{d[:4]}-{d[4:6]}-{d[6:]}T00:00:00Z"
    return {"title": title, "desc": desc, "image": image, "published": published, "url": url}


def article_embed(a):
    emb = {
        "title": trim(a["title"] or "New Rockstar newswire post", 250),
        "url": a["url"],
        "description": trim(a["desc"], 600),
        "color": BRAND_COLOR,
        "footer": {"text": FOOTER},
    }
    if a.get("image"):
        emb["image"] = {"url": a["image"]}
    if a.get("published") and re.match(r"\d{4}-\d{2}-\d{2}", a["published"]):
        emb["timestamp"] = a["published"] if "T" in a["published"] else a["published"] + "T00:00:00Z"
    return emb


def collect_from_html(text, base):
    """Return ordered dict of key -> info for everything of interest on a page."""
    found = {}
    for m in NEWS_RE.finditer(text):
        found.setdefault(f"news:{m.group(1).lower()}", {"kind": "news", "id": m.group(1).lower()})
    for m in VI_PAGE_RE.finditer(text):
        path = m.group(1).strip("/")
        if path.startswith("_next") or re.search(r"\.(js|css|png|jpe?g|webp|svg|ico|json|zip|mp4)$", path, re.I):
            continue
        found.setdefault(f"page:/VI/{path}".lower(), {"kind": "page", "url": f"{SITE}/VI/{path}"})
    for m in MEDIA_RE.finditer(text):
        name = m.group(2)
        found.setdefault(f"media:{name}".lower(), {"kind": "media", "name": name, "url": SITE + m.group(1)})
    if "store.rockstargames.com" in base:
        for m in STORE_RE.finditer(text):
            href = m.group(1)
            url = href if href.startswith("http") else STORE + href
            found.setdefault(f"store:{urllib.parse.urlparse(url).path}".lower(), {"kind": "store", "url": url})
    return found


# ------------------------------------------------------------- summaries ---
SUMMARY_SYSTEM = (
    "You summarise one official Rockstar Games page for a spoiler-sensitive fan Discord. "
    "Use ONLY the PAGE TEXT. Never add outside knowledge. Write at most 3 bullets, each under 22 words: "
    "what is new, the dates, and where to get or see it. If the page reveals story details (plot, character arcs, "
    "mission content, endings), set contains_story to true and leave bullets empty. Never copy long passages. "
    'Reply as JSON only: {"bullets": [string], "contains_story": boolean}.'
)


def page_text(page_html, limit=6000):
    t = re.sub(r"(?is)<(script|style|noscript|svg|head)\b.*?</\1>", " ", page_html or "")
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    return trim(t, limit)


def gemini_json(prompt):
    body = {
        "systemInstruction": {"parts": [{"text": SUMMARY_SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 800, "responseMimeType": "application/json"},
    }
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{urllib.parse.quote(GEMINI_MODEL)}:generateContent",
        data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": GEMINI_KEY, "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=40) as r:
        data = json.load(r)
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(re.sub(r"^```(?:json)?|```$", "", text.strip()).strip())


def maybe_summarise(art, page_html):
    """Post a short AI TL;DR under a newswire post. Never raises: the main post is already out."""
    if not GEMINI_KEY:
        return
    try:
        body = page_text(page_html)
        if len(body) + len(art.get("desc", "")) < 80:
            return
        out = gemini_json(f"TITLE: {art['title']}\nPAGE TEXT: {art.get('desc', '')} {body}")
        if out.get("contains_story"):
            post({"content": "ℹ️ That post includes story details, so there is no summary here. "
                             "Read it on Rockstar's page, or discuss it in #spoiler-zone.", "_norecent": True})
            return
        bullets = [trim(str(b), 220) for b in (out.get("bullets") or [])][:3]
        bullets = [b for b in bullets if b]
        if not bullets:
            return
        post({"content": "🧠 **TL;DR** (AI summary of Rockstar's page, always check the link)\n"
                         + "\n".join("• " + b for b in bullets), "_norecent": True})
    except Exception as e:
        print(f"  summary skipped: {e}")


# --------------------------------------------------------------- sources ---
def poll_youtube(state, backfill):
    xml = http_get(YT_FEED.format(YT_CHANNEL_ID), "application/atom+xml")
    ns = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
          "m": "http://search.yahoo.com/mrss/"}
    root = ET.fromstring(xml)
    feed_title = (root.findtext("a:title", default="", namespaces=ns) or "")
    if "rockstar" not in feed_title.lower():
        raise RuntimeError(f"YouTube channel {YT_CHANNEL_ID} is '{feed_title}', not Rockstar Games. "
                           "Set YT_CHANNEL_ID to the right id.")
    entries = []
    for e in root.findall("a:entry", ns):
        vid = e.findtext("yt:videoId", default="", namespaces=ns)
        title = e.findtext("a:title", default="", namespaces=ns)
        desc = e.findtext("m:group/m:description", default="", namespaces=ns)
        pub = e.findtext("a:published", default="", namespaces=ns)
        if vid:
            entries.append({"id": vid, "title": title, "desc": desc, "published": pub})
    relevant = [e for e in entries if not YT_ONLY_GTA6 or GTA6_PATTERN.search(e["title"] + " " + e["desc"][:400])]
    seen = set(state["youtube"])
    new = [e for e in relevant if e["id"] not in seen]
    if not state["seeded"]:
        to_post = new[:backfill] if backfill else []
    else:
        to_post = new
    posted = 0
    for e in reversed(to_post):  # oldest first
        post({"content": f"🎬 **New from Rockstar Games on YouTube**\n{e['title']}\nhttps://www.youtube.com/watch?v={e['id']}",
              "_ping": True})
        posted += 1
    state["youtube"] += [e["id"] for e in entries if e["id"] not in seen]
    return posted


def poll_site(state, backfill):
    current = {}
    ok_pages = 0
    errors = []
    for url in WATCH_PAGES:
        try:
            text = http_get(url, "text/html")
        except Exception as e:
            errors.append(str(e))
            continue
        ok_pages += 1
        for k, v in collect_from_html(text, url).items():
            current.setdefault(k, v)
    if ok_pages == 0:
        raise RuntimeError("; ".join(errors)[:400])
    seen = set(state["site"])
    new_keys = [k for k in current if k not in seen]
    first_run = not state["seeded"]
    to_post = []
    if first_run:
        news = [k for k in new_keys if k.startswith("news:")]
        to_post = news[:backfill] if backfill else []
    else:
        to_post = new_keys
    posted = 0
    media_batch = []
    marked = set(new_keys) if first_run else set()
    for k in reversed(to_post):  # page order is newest first; post oldest first
        info = current[k]
        if posted >= MAX_SITE_POSTS_PER_RUN:
            break
        kind = info["kind"]
        if kind == "news":
            url = f"{SITE}/newswire/article/{info['id']}"
            try:
                page_html = http_get(url, "text/html")
                art = parse_article(page_html, url)
            except Exception as e:
                print(f"  could not read article {url}: {e}")
                continue  # not marked as seen, so it is retried next run
            post({"content": "📰 **New on Rockstar Newswire**", "embeds": [article_embed(art)], "_ping": True})
            posted += 1
            if not first_run or backfill:
                maybe_summarise(art, page_html)
        elif kind == "page":
            post({"content": "🆕 **New page on Rockstar's GTA VI site**",
                  "embeds": [{"title": info["url"].replace("https://www.", ""), "url": info["url"],
                              "color": BRAND_COLOR, "footer": {"text": FOOTER}}]})
            posted += 1
        elif kind == "store":
            post({"content": "🛒 **New in the Rockstar Store (GTA VI)**", "embeds": [{
                "title": info["url"].replace("https://", ""), "url": info["url"],
                "color": BRAND_COLOR, "footer": {"text": FOOTER}}]})
            posted += 1
        elif kind == "media":
            media_batch.append(info)
        marked.add(k)
    if media_batch:
        names = ", ".join(i["name"].replace("_", " ") for i in media_batch[:10])
        more = f" (+{len(media_batch) - 10} more)" if len(media_batch) > 10 else ""
        post({"content": "🖼️ **New artwork, screenshots or trailer art on Rockstar's media page**",
              "embeds": [{"title": "GTA VI media and downloads", "url": f"{SITE}/VI/media",
                          "description": trim(names + more, 600), "image": {"url": media_batch[0]["url"]},
                          "color": BRAND_COLOR, "footer": {"text": FOOTER}}]})
        posted += 1
    state["site"] = list(dict.fromkeys(state["site"] + sorted(marked)))
    return posted


def poll_google_news(state):
    xml = http_get(GOOGLE_NEWS, "application/rss+xml")
    root = ET.fromstring(xml)
    items = []
    for it in root.iter("item"):
        guid = it.findtext("guid") or it.findtext("link") or ""
        items.append({"guid": guid, "title": it.findtext("title") or "", "link": it.findtext("link") or "",
                      "date": it.findtext("pubDate") or ""})
    seen = set(state["gnews"])
    new = [i for i in items if i["guid"] and i["guid"] not in seen]
    posted = 0
    if state["seeded"]:
        for i in reversed(new[:3]):
            post({"content": "📰 **Rockstar update (via Google News, direct site check was unavailable)**\n"
                             f"{trim(i['title'], 200)}\n{i['link']}"})
            posted += 1
    state["gnews"] += [i["guid"] for i in new]
    return posted


# ------------------------------------------------------------------ main ---
def run(backfill=0):
    global NO_PING
    state = load_state()
    NO_PING = not state["seeded"]
    total = 0
    problems = []

    try:
        total += poll_youtube(state, backfill)
        state["fail"]["youtube"] = 0
    except Exception as e:
        state["fail"]["youtube"] += 1
        print(f"YouTube source failed ({state['fail']['youtube']}x): {e}")
        if state["fail"]["youtube"] == ALERT_AFTER_FAILURES:
            problems.append(f"YouTube: {e}")

    if os.environ.get("SITE_PAGES", "1") != "0":
        try:
            total += poll_site(state, backfill)
            state["fail"]["site"] = 0
        except Exception as e:
            state["fail"]["site"] += 1
            print(f"Rockstar site source failed ({state['fail']['site']}x): {e}")
            try:
                total += poll_google_news(state)
                print("  fallback: Google News checked")
            except Exception as e2:
                print(f"  fallback also failed: {e2}")
            if state["fail"]["site"] == ALERT_AFTER_FAILURES:
                problems.append(f"Rockstar site: {e}")

    if not state["seeded"]:
        state["seeded"] = True
        print("First run: existing items were recorded without posting. "
              "New items from now on will be posted." if not backfill else
              f"First run: recorded existing items and posted up to {backfill} per source.")
    if not DRY:
        save_state(state)
    print(f"Done. Posted {total} message(s).")
    if problems:
        print("ATTENTION (this run fails on purpose so GitHub emails you once):\n  " + "\n  ".join(problems))
        return 1
    return 0


def main():
    global DRY
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print what would be posted; change nothing")
    ap.add_argument("--test-webhook", action="store_true", help="send one test message and exit")
    ap.add_argument("--backfill", type=int, default=0, help="on the very first run also post the newest N items per source")
    args = ap.parse_args()
    DRY = args.dry_run
    if args.test_webhook:
        post({"content": "✅ Rockstar HQ feed is connected. You will see new GTA VI posts from Rockstar here."})
        print("Test message sent.")
        return 0
    return run(args.backfill)


if __name__ == "__main__":
    sys.exit(main())
