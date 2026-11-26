"""Console code the user runs on SportyBet's own page, in their own browser.

SportyBet refuses requests that don't come from a real browser session, so the app never contacts it.
Instead it writes small scripts: the user pastes one into the browser console on sportybet.com, it fetches
the data (one request every 1.5 seconds) and downloads it as a file, and the user uploads that file here.

SportyBet replaces the page's fetch() with a wrapper that rewrites addresses, so the scripts borrow an
untouched fetch from a blank frame.
"""
import json
import re

BASE = "https://www.sportybet.com/api/gh"
EVENT_API = BASE + "/factsCenter/event"
LEAGUE_API = BASE + "/factsCenter/pcEvents"
DIRECTORY_API = BASE + "/factsCenter/popularAndSportList?sportId=sr%3Asport%3A1"
CODE_API = BASE + "/orders/share/"
HUB_API = BASE + "/orders/bookingCode/filter"     # the list behind sportybet.com/gh/m/code-hub/codes

# SportyBet's own list page asks for 1,18,10,29,11,26,36,14. The same request also accepts team totals,
# bookings and corners (tested on the Premier League, Oct 2026), so a league import carries all three families.
LIST_MARKETS = ("1,18,10,29,11,26,36,14,"      # list-page defaults
                "19,20,"                        # home / away goal totals
                "139,136,900304,900305,"        # bookings: total, 1X2, home, away
                "166,162,900300,900301")        # corners: total, 1X2, home, away
PAUSE_MS = 150


def _fname(prefix, ident):
    return f"{prefix}_{re.sub(r'[^A-Za-z0-9]+', '_', ident).strip('_')}.json"


class Snippet(str):
    """Console code (the string itself) that also carries its list of requests, so the same fetch can be
    handed to the CodeMatch bookmark button instead."""
    requests: list = []
    label: str = ""


def fetch_snippet(requests_, filename):
    """requests_ = [{'label', 'url', 'body' (optional, for POST)}]. Saves every OK response in one file."""
    reqs = json.dumps(requests_, indent=None)
    code = f"""{{
const frame = document.body.appendChild(document.createElement("iframe"));
frame.style.display = "none";
const cleanFetch = frame.contentWindow.fetch.bind(window);
const headers = {{ clientid: "web", operid: "3", platform: "web" }};
const reqs = {reqs};
const out = [];
for (const [i, q] of reqs.entries()) {{
  const opts = q.body
    ? {{ method: "POST", credentials: "include", headers: {{ ...headers, "content-type": "application/json" }}, body: q.body }}
    : {{ credentials: "include", headers }};
  try {{
    const r = await cleanFetch(q.url, opts);
    const t = await r.text();
    console.log((i + 1) + "/" + reqs.length, q.label, "status", r.status);
    if (r.ok) out.push(t);
  }} catch (e) {{ console.log((i + 1) + "/" + reqs.length, q.label, "failed:", e.message); }}
  if (i < reqs.length - 1) await new Promise(res => setTimeout(res, {PAUSE_MS}));
}}
if (out.length) {{
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([out.join("\\n")], {{ type: "application/json" }}));
  a.download = "{filename}";
  a.click();
}}
console.log("saved", out.length, "of", reqs.length, "responses to {filename}");
}}"""
    snip = Snippet(code)
    snip.requests = requests_
    snip.label = requests_[0]["label"] if len(requests_) == 1 else f"{len(requests_)} requests"
    return snip


def leagues_snippet(leagues):
    """leagues = [(tournament_id, name)]. One request per league."""
    reqs = [{"label": name or tid, "url": LEAGUE_API,
             "body": json.dumps([{"sportId": "sr:sport:1", "marketId": LIST_MARKETS, "tournamentId": [[tid]]}])}
            for tid, name in leagues]
    fname = _fname("league", leagues[0][0]) if len(leagues) == 1 else f"leagues_{len(leagues)}.json"
    return fetch_snippet(reqs, fname)


def events_snippet(games):
    """games = [(event_id, label)]. Full market list for each game."""
    reqs = [{"label": label or eid, "url": f"{EVENT_API}?productId=3&eventId={eid.replace(':', '%3A')}"}
            for eid, label in games]
    fname = _fname("game", games[0][0]) if len(games) == 1 else f"games_{len(games)}.json"
    return fetch_snippet(reqs, fname)


def codes_snippet(codes):
    reqs = [{"label": c, "url": CODE_API + c} for c in codes]
    return fetch_snippet(reqs, _fname("code", codes[0]) if len(codes) == 1 else f"codes_{len(codes)}.json")


def hub_snippet(days=3, pages=3, odds=(1, None), legs=(1, 50), today=None):
    """Code Hub lists: the most popular shared codes for the next `days` days (today included), `pages` pages of
    about 20 codes each. Each list already holds every code's picks with odds and probabilities, so this is the whole
    fetch. The body copies what SportyBet's own Code Hub page sends; 'i' is taken to be the page number."""
    import datetime
    today = today or datetime.datetime.now(datetime.timezone.utc).date()
    midnight = lambda d: int(datetime.datetime(d.year, d.month, d.day, tzinfo=datetime.timezone.utc).timestamp())
    days_ = [midnight(today + datetime.timedelta(days=k)) for k in range(max(1, min(days, 7)))]
    lo, hi = odds
    body = lambda i: json.dumps({"defaultList": True, "featureCodeMarket": "NON_BB",
                                 "foldsFilter": [int(legs[0]), int(legs[1])], "i": i,
                                 "oddsFilter": [max(1, int(lo or 1)), -int(-(hi or 2147483647) // 1)],
                                 "sortBy": {"index": 0, "field": "popularity", "order": "desc"},
                                 "timeFilter": days_})
    reqs = [{"label": f"Code Hub page {i + 1}", "url": HUB_API, "body": body(i)} for i in range(max(1, min(pages, 10)))]
    return fetch_snippet(reqs, f"codehub_{today.isoformat()}.json")


MAKE_API = BASE + "/orders/share"


def make_code_requests(selections, part=None):
    """The request that asks SportyBet to turn picks into a booking code. selections = [{eventId, marketId,
    specifier, outcomeId}]: the same fields SportyBet uses when it describes a code. It only creates a code; it
    never places a bet. part: (i, k) when this is code i of k made in one go."""
    sels = [{"eventId": s["eventId"], "marketId": s["marketId"], "specifier": s.get("specifier") or None,
             "outcomeId": s["outcomeId"]} for s in selections]
    which = f"make booking code {part[0]} of {part[1]}" if part and part[1] > 1 else "make a booking code"
    return [{"label": f"{which} ({len(sels)} pick{'s' if len(sels) != 1 else ''})",
             "url": MAKE_API, "body": json.dumps({"selections": sels})}]


def split_evenly(items, per):
    """items in ceil(len / per) runs of near-equal size, in order: 51 picks at 50 a code become 26 and 25."""
    if not items:
        return []
    k = -(-len(items) // max(1, per))
    size, extra = divmod(len(items), k)
    out, i = [], 0
    for j in range(k):
        n = size + (1 if j < extra else 0)
        out.append(items[i:i + n])
        i += n
    return out


def directory_snippet():
    return fetch_snippet([{"label": "league directory", "url": DIRECTORY_API}], "league_directory.json")


# ---------- the CodeMatch bookmark button ----------
# A bookmarklet the user drags to the bookmarks bar once. Clicked on sportybet.com, it asks the CodeMatch app on
# this computer what to fetch, fetches it with the user's own SportyBet session, and posts each response back.
# On a match page with nothing queued, it fetches that game. Everything it sends goes to the user's own app.
BUTTON_VERSION = "3"     # raise when the bookmark's code changes, so the app can ask for a fresh one
# v3: guard against clicking bookmark on non-sportybet tabs with direct instructions
BOOKMARKLET = r"""(async()=>{const A=%(base)s,K=%(key)s,V=%(version)s,d=document,P=150;
let b=d.getElementById("cm-box");if(!b){b=d.body.appendChild(d.createElement("div"));b.id="cm-box"}
b.style.cssText="position:fixed;z-index:2147483647;right:16px;bottom:16px;max-width:380px;padding:12px 16px;border-radius:10px;background:#16211c;color:#f2f4f1;font:14px/1.45 system-ui,sans-serif;box-shadow:0 8px 28px rgba(0,0,0,.35)";
const say=t=>{b.textContent="CodeMatch: "+t};
if(!location.hostname.includes("sportybet.com")){say("Please click this bookmark on SportyBet (sportybet.com)! On CodeMatch, click 'Fetch with CodeMatch button' first, which opens SportyBet, then click this bookmark there.");return}
const f=d.body.appendChild(d.createElement("iframe"));f.style.display="none";
const F=f.contentWindow.fetch.bind(window),H={clientid:"web",operid:"3",platform:"web"};
const post=(p,body)=>F(A+p+(p.includes("?")?"&":"?")+"k="+K,{method:"POST",headers:{"content-type":"text/plain"},body});
let keep=12000;
try{say("asking the app what to fetch...");
let j=await(await F(A+"bridge/job?v="+V+"&k="+K)).json();
if(!j.requests||!j.requests.length){const m=decodeURIComponent(location.pathname).match(/sr:match:\d+/);
if(!m){say(j.message||"nothing to fetch. Choose something in CodeMatch first.");return}
j={id:"",requests:[{label:"this game",url:location.origin+"/api/gh/factsCenter/event?productId=3&eventId="+encodeURIComponent(m[0])}]}}
let ok=0,bad=0;const R=j.requests;
for(let i=0;i<R.length;i++){const q=R[i];say((i+1)+" of "+R.length+": "+q.label);
try{const r=await F(q.url,q.body?{method:"POST",credentials:"include",headers:{...H,"content-type":"application/json"},body:q.body}:{credentials:"include",headers:H});
const t=await r.text();
if(!r.ok){bad++;await post("bridge/import?job="+j.id+"&refused="+r.status+"&label="+encodeURIComponent(q.label),t.slice(0,300))}
else{
try{const res=await post("bridge/import?job="+j.id,t);
const x=await res.json();
if(x.add&&x.add.length)R.push(...x.add);
ok++}catch(e){bad++}
}}catch(e){bad++}
if(i<R.length-1)await new Promise(s=>setTimeout(s,P))}
const s=await(await post("bridge/done?job="+j.id+"&failed="+bad,"")).json();
say("done. "+s.summary+(bad?" "+bad+" request"+(bad>1?"s":"")+" failed.":"")+" Go back to the CodeMatch tab.")}
catch(e){keep=30000;say("couldn't reach the app at "+A+". Is CodeMatch running on this computer? If the browser asks to access devices on your local network, choose Allow. ("+e.message+")")}
finally{f.remove();setTimeout(()=>b.remove(),keep)}})();"""


def bookmarklet(base_url, key):
    """The javascript: link for the bookmarks bar, pointing at this app with this app's secret key."""
    from urllib.parse import quote
    code = BOOKMARKLET % {"base": json.dumps(base_url.rstrip("/") + "/"), "key": json.dumps(key),
                          "version": json.dumps(BUTTON_VERSION)}
    return "javascript:" + quote(code, safe="(){}[];,.=:+-*/!?&|<>'\"_$")
