import json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import rockstar_hq_poster as P

tmp = tempfile.mkdtemp()
P.STATE_FILE = os.path.join(tmp, "state.json")
P.RECENT_FILE = os.path.join(tmp, "recent.json")
P.WEBHOOK = "https://discord.test/hook"
P.PING_ROLE_ID = "123"
sent = []
P.post_orig = P.post
P.http_post_json = lambda url, payload: sent.append(payload) or 204
P.time.sleep = lambda s: None

def yt(entries):
    items = "".join(f"""<entry><yt:videoId>{i}</yt:videoId><title>{t}</title><published>2026-11-0{n+1}T10:00:00+00:00</published>
    <media:group><media:description>{d}</media:description></media:group></entry>""" for n,(i,t,d) in enumerate(entries))
    return f"""<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns:media="http://search.yahoo.com/mrss/">
    <title>Rockstar Games</title>{items}</feed>""".replace("media:group","m:group").replace("media:description","m:description").replace('xmlns:media=','xmlns:m=')

def art(title, desc, img="https://media.rockstargames.com/x.jpg"):
    return f"""<html><head><title>{title} - Rockstar Games</title><meta property="og:title" content="{title} - Rockstar Games">
    <meta property="og:description" content="{desc}"><meta property="og:image" content="{img}"></head></html>"""

pages = {}
def fake_get(url, accept="*/*"):
    if url in pages:
        v = pages[url]
        if isinstance(v, Exception): raise v
        return v
    raise RuntimeError("404 " + url)
P.http_get = fake_get

yt_url = P.YT_FEED.format(P.YT_CHANNEL_ID)
home = '<a href="/newswire/article/k4ak9okk485712">a</a><a href="/newswire/article/39ak8a12395591">b</a><a href="/VI/music">m</a><a href="/VI/only-in-leonida">o</a><script>"/VI/media"</script>'
media = '<img src="/VI/_next/static/media/GTAVI_Launch_Trailer_poster.0_q-sdrgufc.s.jpg?akim=1"><img src="https://www.rockstargames.com/VI/_next/static/media/Jason_Duval_07.0ca326xbl~oyh.jpg">'
pages.update({
 yt_url: yt([("v1","Grand Theft Auto VI Trailer 2","trailer"),("v2","Red Dead Redemption 2 update","rdr")]),
 P.SITE+"/VI": home, P.SITE+"/VI/media": media, P.SITE+"/VI/music": "<html/>", P.SITE+"/VI/only-in-leonida": "<html/>",
 P.SITE+"/newswire?tag=vi": '<a href="/newswire/article/517572321a549a">launch</a>',
 P.STORE+"/grand-theft-auto-vi-collection": '<a href="/products/grand-theft-auto-vi-hoodie">h</a>',
 P.SITE+"/newswire/article/k4ak9okk485712": art("Grand Theft Auto VI Pre-Load Begins on November 10","Pre-load begins November 10."),
 P.SITE+"/newswire/article/39ak8a12395591": art("Original Score by Justice","The score is composed by Justice."),
 P.SITE+"/newswire/article/517572321a549a": art("Watch the Grand Theft Auto VI Launch Trailer","Vice City, USA."),
 P.SITE+"/newswire/article/newone0000abcd": art("Grand Theft Auto VI Leonida Map Is Here","Download the map."),
})

def run(backfill=0):
    sent.clear()
    code = P.run(backfill)
    return code, list(sent)

# 1: first run seeds silently
c, s = run(); assert c == 0 and s == [], (c, s)
st = json.load(open(P.STATE_FILE)); assert st["seeded"] and "news:k4ak9okk485712" in st["site"] and "v1" in st["youtube"] and "v2" in st["youtube"]
assert "page:/vi/music" in st["site"] and "media:gtavi_launch_trailer_poster" in st["site"] and "store:/products/grand-theft-auto-vi-hoodie" in st["site"], st["site"]
print("1 seed ok:", len(st["site"]), "site keys")
# 2: nothing new
c, s = run(); assert s == [] and c == 0
print("2 idempotent ok")
# 3: new video, new article (appears first on home), new media image, new page
pages[yt_url] = yt([("v3","Grand Theft Auto VI: Gameplay","g"),("v1","Grand Theft Auto VI Trailer 2","trailer"),("v2","Red Dead Redemption 2 update","rdr")])
pages[P.SITE+"/VI"] = '<a href="/newswire/article/newone0000abcd">n</a>' + home + '<a href="/VI/map">map</a>'
pages[P.SITE+"/VI/media"] = media + '<img src="/VI/_next/static/media/Leonida_Map_poster.0abc.jpg">'
c, s = run(); assert c == 0
kinds = [x.get("content","") for x in s]
print("3 posted:", kinds)
assert any("YouTube" in k for k in kinds) and any("Newswire" in k for k in kinds) and any("media" in k for k in kinds) and any("New page" in k for k in kinds)
news = [x for x in s if "Newswire" in x["content"]][0]
assert news["embeds"][0]["title"] == "Grand Theft Auto VI Leonida Map Is Here" and news["embeds"][0]["description"] == "Download the map."
assert news["content"].startswith("<@&123>") and news["allowed_mentions"] == {"roles": ["123"]}
assert not any("Red Dead" in json.dumps(x) for x in s)
print("   embed ok, ping ok, RDR filtered")
# 4: same again -> nothing
c, s = run(); assert s == []
# 5: site blocked -> fallback + failure counting + one loud failure
for u in P.WATCH_PAGES: pages[u] = RuntimeError("403")
pages[P.GOOGLE_NEWS] = "<rss><channel><item><guid>g1</guid><title>Rockstar posts a thing</title><link>https://news.google.com/x</link></item></channel></rss>"
codes = []
for i in range(9):
    c, s = run(); codes.append(c)
print("5 codes:", codes)
assert codes.count(1) == 1 and codes[7] == 1
# 6: site recovers -> failure counter resets
for u in P.WATCH_PAGES: pages.pop(u)
pages.update({P.SITE+"/VI": home + '<a href="/newswire/article/newone0000abcd">n</a>', P.SITE+"/VI/media": media, P.SITE+"/VI/music":"<html/>", P.SITE+"/VI/only-in-leonida":"<html/>", P.SITE+"/newswire?tag=vi":"<html/>", P.STORE+"/grand-theft-auto-vi-collection":"<html/>"})
c, s = run(); assert json.load(open(P.STATE_FILE))["fail"]["site"] == 0
print("6 recovery ok")
# 7: backfill on a fresh state posts newest N articles only
os.remove(P.STATE_FILE)
c, s = run(backfill=2)
print("7 backfill posted:", [x["content"][:30] for x in s])
assert len([x for x in s if "Newswire" in x["content"]]) == 2 and not any(x["content"].startswith("<@&") for x in s)
print("ALL TESTS PASSED")

# recent.json: newest first, has title and link, capped at 20
rec = json.load(open(P.RECENT_FILE))
assert rec and all(("title" in r and "url" in r and "t" in r) for r in rec), rec
assert len(rec) <= 20
assert any("Leonida Map" in r["title"] for r in rec), rec
print("recent.json ok:", len(rec), "items; newest:", rec[0]["title"][:50])

# ---- summaries (Gemini is faked; no network) ----
import importlib
tmp2 = tempfile.mkdtemp()
P.STATE_FILE = os.path.join(tmp2, "state.json"); P.RECENT_FILE = os.path.join(tmp2, "recent.json")
long_page = lambda title, body: f"""<html><head><title>{title} - Rockstar Games</title><meta property="og:title" content="{title}">
<meta property="og:description" content="{body[:120]}"></head><body><script>var x=1;</script><p>{body}</p></body></html>"""
pages[P.SITE+"/newswire/article/sum1sum1sum1ab"] = long_page("Grand Theft Auto VI Merch Drop", "The Rockstar Store opens a new GTA VI merchandise collection on 12 November with tees, caps and tote bags available worldwide.")
pages[P.SITE+"/newswire/article/sum2sum2sum2ab"] = long_page("A Deep Look at Chapter Two", "In this chapter Jason betrays Lucia during the second mission and the ending reveals who survives the heist at the end of the story.")
pages[P.SITE+"/newswire/article/sum3sum3sum3ab"] = long_page("Another News Post", "Plenty of words here so that the page has enough text to be worth summarising, honestly, a decent amount of text.")
home2 = '<a href="/newswire/article/sum1sum1sum1ab">a</a><a href="/newswire/article/sum2sum2sum2ab">b</a><a href="/newswire/article/sum3sum3sum3ab">c</a>' + home
pages[P.SITE+"/VI"] = home2
calls = []
def fake_gemini(prompt):
    calls.append(prompt)
    if "Merch Drop" in prompt: return {"bullets": ["New GTA VI merch collection.", "Opens 12 November.", "At the Rockstar Store."], "contains_story": False}
    if "Chapter Two" in prompt: return {"bullets": ["Jason betrays Lucia"], "contains_story": True}
    raise RuntimeError("quota")
P.gemini_json = fake_gemini
st = json.load(open(P.STATE_FILE)) if os.path.exists(P.STATE_FILE) else None
# seed silently first (no summaries for what already exists), then new items arrive
P.GEMINI_KEY = ""
pages[P.SITE+"/VI"] = home          # original home: seeds the state
c, s = run(); assert s == []
pages[P.SITE+"/VI"] = home2
# 8: no key -> news posted, no summaries
c, s = run(); texts = [x.get("content", "") for x in s]
assert sum("New on Rockstar Newswire" in t for t in texts) == 3 and not any("TL;DR" in t or "summary here" in t for t in texts), texts
print("8 no key: no summaries ok")
# reset state to test with key
os.remove(P.STATE_FILE); pages[P.SITE+"/VI"] = home; run(); pages[P.SITE+"/VI"] = home2
P.GEMINI_KEY = "k"
c, s = run(); texts = [x.get("content", "") for x in s]
assert any("TL;DR" in t and "Opens 12 November" in t for t in texts), texts
assert any("includes story details" in t and "Jason" not in t for t in texts), texts      # story page: notice only, no bullets leaked
assert sum("New on Rockstar Newswire" in t for t in texts) == 3, texts                   # a Gemini failure did not stop the post
assert not any("betrays" in t.lower() for t in texts)
print("9 summaries ok: TL;DR posted, story page gets a notice, failure tolerated")
rec = json.load(open(P.RECENT_FILE))
assert not any("TL;DR" in r["title"] or "story details" in r["title"] for r in rec), rec    # summaries do not pollute /whatsnew
print("10 recent.json ignores summaries ok")
print("SUMMARY TESTS PASSED")
