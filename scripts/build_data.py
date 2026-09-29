#!/usr/bin/env python3
"""Rebuild data/ping_dashboard_data.json from a Slate "Pings" query export.

Usage:
    python3 scripts/build_data.py "path/to/Pings Query.csv"
    python3 scripts/build_data.py export.csv --out data/ping_dashboard_data.json

Expected CSV columns, in this order:
    Ping Referrer, Ping URL, Ping Timestamp, Ping Duration (seconds), Ping IP Address,
    Ping Identity, Ping UTM Campaign, Ping UTM Content, Ping UTM Medium, Ping UTM Source, Ping UTM Term

The output holds only aggregates (counts by day/week/section/channel/program).
No IP addresses, URLs with query strings, or row-level records are written.
Needs pandas and numpy; about 4 GB RAM for a ~2M-row export.
"""
import argparse, gc, json, math, os
import numpy as np
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("csv")
ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "data", "ping_dashboard_data.json"))
ap.add_argument("--hosts", default="apply.dal.ca,www.dal.ca,virtualtour.dal.ca",
                help="comma-separated hosts to keep; other hosts are dropped as noise")
args = ap.parse_args()
HOSTS = args.hosts.split(",")

# ---------- load ----------
df = pd.read_csv(args.csv, encoding="utf-8-sig", low_memory=False, dtype=str)
df.columns = ["ref", "url", "ts", "dur", "ip", "pid", "camp", "content", "medium", "source", "term"]
df["ts"] = pd.to_datetime(df["ts"], format="ISO8601")
df["dur"] = pd.to_numeric(df["dur"], errors="coerce")
u = df["url"].str.extract(r"^https?://([^/?#]+)([^?#]*)")
df["host"] = u[0].str.lower()
df["path"] = u[1].str.lower().str.rstrip("/")
df["refhost"] = df["ref"].str.extract(r"^https?://([^/?#]+)")[0].str.lower()

dq = {"rows": len(df), "pid_unique": int(df.pid.nunique())}
dq["date_only"] = int((df.ts.dt.hour.eq(0) & df.ts.dt.minute.eq(0) & df.ts.dt.second.eq(0)).sum())
dq["dur_missing"] = int(df.dur.isna().sum())
dq["dur_cap"] = int((df.dur >= 3500).sum())
okhost = df.host.isin(HOSTS)
dq["other_hosts"] = int((~okhost).sum())
dq["broken_utm"] = int(df.url.str.contains("%3Futm_", regex=False, na=False).sum())
dq["utm_rows"] = int(df.source.notna().sum())
df = df[okhost].copy()
dq["utm_in_url"] = int(df.url.str.contains("utm_", case=False, na=False).sum())
df["clk"] = df.url.str.contains("gclid|gbraid|wbraid|msclkid|gad_source", case=False, na=False)
df.drop(columns=["ref", "url", "content", "term"], inplace=True)
gc.collect()

# ---------- page sections ----------
h, p = df.host, df.path.fillna("")
S = p.str.startswith
df["cat"] = np.select([
    h.eq("virtualtour.dal.ca"),
    h.eq("www.dal.ca") & S("/study/programs/"),
    h.eq("www.dal.ca") & p.eq("/study/programs.html"),
    h.eq("www.dal.ca") & (p.str.contains("international") | p.str.match(r"^/dal/(nigeria|india|usa|bangladesh|middle-east|africa|china|pathways)")),
    h.eq("www.dal.ca"),
    S("/portal/reader") | p.eq("/apply/viewer") | S("/portal/graduate-user") | S("/portal/graduate-student-progress"),
    S("/account"),
    p.eq("/apply"),
    p.isin(["/apply/frm", "/apply/form", "/apply/update", "/apply/review", "/apply/certify"]) | S("/portal/app_start"),
    p.eq("/apply/payment"),
    p.eq("/apply/status") | S("/portal/app_status") | p.eq("/apply/download.pdf"),
    p.eq("/portal/open-house") | S("/register") | p.str.contains("tour") | p.eq("/portal/future-student-events"),
    p.eq("/portal/program-explorer"),
    p.isin(["/apply/ref", "/apply/refer"]),
], ["Virtual tours", "Program pages", "Program finder", "International pages", "Other dal.ca pages",
    "Staff / reviewer tools", "Login & account", "Application hub", "Application form", "Payment", "Status portal",
    "Events & open house", "Program explorer", "References"], "Other portal pages")
df["isstaff"] = df.cat.eq("Staff / reviewer tools")

# ---------- staff & bot flag ----------
g = df.groupby("ip").agg(n=("pid", "size"), md=("dur", "median"), np_=("path", "nunique"), staff=("isstaff", "mean"))
bots = set(g[(g.n >= 200) & (g.np_ >= 100) & (g.md <= 3)].index) | set(g[g.index.str.startswith("10.")].index)
staffip = set(g[g.staff >= 0.2].index)
df["noise"] = df.ip.isin(bots) | df.ip.isin(staffip) | df.isstaff
dq["bot_ips"], dq["staff_ips"], dq["noise_rows"] = len(bots), len(staffip), int(df.noise.sum())

# ---------- visits (IP + 30 min gap) ----------
df = df.sort_values(["ip", "ts"]).reset_index(drop=True)
gap = df.ts.diff().dt.total_seconds()
df["sid"] = ((df.ip != df.ip.shift()) | (gap > 1800)).cumsum()
df["step"] = df.groupby("sid").cumcount()

# ---------- channels ----------
rh = df.refhost.fillna(""); src = df.source.fillna("").str.lower(); med = df.medium.fillna("").str.lower()
search = rh.str.contains(r"(?:google\.|bing\.|yahoo\.|duckduckgo|ecosia|baidu|yandex|naver|search\.brave)") & ~rh.str.contains("mail.google")
df["ch"] = np.select([
    rh.str.contains("pangle") | med.eq("tt") | src.str.contains("tiktok") | rh.str.contains("tiktok"),
    rh.str.contains(r"chatgpt|perplexity|copilot|gemini|claude\.ai|openai") | src.str.contains(r"chatgpt|perplexity|copilot|openai"),
    (search | med.isin(["search", "pmax", "cpc", "ppc"])) & (df.clk | df.camp.notna() | med.isin(["pmax", "cpc", "ppc"])),
    search | med.eq("search"),
    rh.str.contains(r"facebook|instagram|linkedin|reddit|youtube|twitter|x\.com|t\.co|snapchat|threads") | src.str.contains(r"meta|facebook|instagram|organic_fb|organic_ig|linkedin") | med.isin(["paid-social", "social", "organic_social"]),
    rh.str.contains(r"mail\.|outlook|mail\.yahoo") | med.eq("email"),
    rh.str.contains(r"portal\.com|educanada|mynsfuture|myblueprint|chatterhigh|studyinternational|idp|globaladmissions|ouac|studyportals") | src.str.contains(r"studyportals|studyinternational|globaladmissions|idp"),
    rh.isin(["www.dal.ca", "apply.dal.ca", "virtualtour.dal.ca", "dal.ca"]),
    rh.str.endswith("dal.ca") | rh.str.contains(r"touchnet|microsoftonline|ukings"),
    rh.eq(""),
], ["TikTok ads", "AI assistants", "Paid search", "Organic search", "Social", "Email", "Education portals",
    "Within Dal sites", "Dal systems / payment / SSO", "Direct / none"], "Other referrers")
del rh, src, med, search, gap, h, p, S; gc.collect()
for c in ["cat", "host", "path", "refhost", "camp", "source", "medium", "ch"]:
    df[c] = df[c].astype("category")
df["date"] = df.ts.dt.strftime("%Y-%m-%d")
df["wk"] = df.ts.dt.to_period("W-SUN").dt.start_time.dt.strftime("%Y-%m-%d")
df["dow"] = df.ts.dt.dayofweek
df["hr"] = df.ts.dt.hour

out = {"dq": dq, "source": os.path.basename(args.csv)}
cl = lambda s: s.map({False: 0, True: 1})
def grp(frame, by):
    d = frame.groupby(observed=True, by=by).size().reset_index(name="n")
    d["noise"] = cl(d.noise)
    return d.values.tolist()

out["daily"] = grp(df, ["date", "cat", "noise"])
e = df[df.step == 0]
e = e.assign(noise=e.sid.map(df.groupby("sid").noise.max()))
out["entry_daily"] = grp(e, ["date", "ch", "noise"])
out["hw"] = grp(df, ["wk", "dow", "hr", "noise"])
df["db"] = pd.cut(df.dur, [-1, 0, 2, 4, 9, 29, 59, 299, 1e9], labels=range(8)).astype("float").fillna(-1).astype(int)
out["dwell"] = grp(df[df.db >= 0], ["wk", "cat", "db", "noise"])

s0 = e[["sid", "ch", "cat", "wk", "noise"]].astype({"cat": object}).rename(columns={"cat": "c1"})
nxt = df[df.step > 0][["sid", "cat"]]
first_cat = s0.set_index("sid").c1
nxt = nxt[nxt.cat.astype(object).values != first_cat.reindex(nxt.sid).values].drop_duplicates("sid")
s0["c2"] = s0.sid.map(nxt.set_index("sid").cat).astype(object).fillna("(left / stayed)")
out["flow"] = grp(s0, ["wk", "ch", "c1", "c2", "noise"])

t = df[["sid", "cat", "wk", "noise"]].copy(); t["prev"] = t.groupby("sid").cat.shift()
t = t[t.prev.notna() & (t.prev.astype(object) != t.cat.astype(object))]
out["trans"] = grp(t, ["wk", "prev", "cat", "noise"])

ss = df.groupby("sid").agg(wk=("wk", "first"), n=("pid", "size"), noise=("noise", "max"), dur=("dur", "sum"))
ss["pb"] = pd.cut(ss.n, [0, 1, 2, 4, 9, 19, 1e9], labels=range(6)).astype(int)
out["sesslen"] = grp(ss, ["wk", "pb", "noise"])

pr = df[df.cat == "Program pages"].copy()
m = pr.path.astype(str).str.extract(r"^/study/programs/([^/]+)/([^/.]+)")
pr["lvl"] = m[0].map({"undergraduate": "UG", "graduate-professional": "GR"}).fillna("Other"); pr["prog"] = m[1]
out["prog"] = grp(pr, ["wk", "prog", "lvl", "noise"])

c = df[~df.noise]
formips = set(c[c.cat.isin(["Application form", "Payment"])].ip); payips = set(c[c.cat == "Payment"].ip)
aff = []
for (prog, lvl), ips in pr[~pr.noise].groupby(observed=True, by=["prog", "lvl"]).ip:
    ips = set(ips)
    if len(ips) >= 150:
        aff.append([prog, lvl, len(ips), len(ips & formips), len(ips & payips)])
out["aff"] = aff
out["base_aff"] = [int(c.ip.nunique()), len(formips), len(payips)]

EXPLORE = {"Program pages", "Program finder", "Program explorer", "Events & open house", "Virtual tours", "International pages"}
APPLY = {"Application form", "Application hub", "Status portal", "Payment"}
fun, dist = {}, {}
for mode, sub in [(0, df), (1, df[~df.noise])]:
    ipc = sub.groupby("ip").cat.agg(lambda s: set(s.astype(str)))
    stages = [("Any visit", None), ("Portal login / account", "Login & account"), ("Application hub", "Application hub"),
              ("Application form", "Application form"), ("Payment page", "Payment"), ("Status portal", "Status portal")]
    fun[str(mode)] = [[nm, int(len(ipc) if k is None else ipc.map(lambda s: k in s).sum())] for nm, k in stages]
    fun[f"{mode}_explore"] = int(ipc.map(lambda s: bool(s & EXPLORE) and not bool(s & APPLY)).sum())
    a = sub.groupby("ip").agg(n=("pid", "size"), w=("wk", "nunique"), s=("sid", "nunique"))
    cnt = lambda col, b, k: pd.cut(a[col], b, labels=range(k)).astype(int).value_counts().reindex(range(k), fill_value=0).tolist()
    dist[str(mode)] = {"pings": cnt("n", [0, 1, 2, 4, 9, 19, 49, 99, 1e9], 8),
                       "weeks": cnt("w", [0, 1, 2, 3, 5, 9, 1e9], 6),
                       "sess": cnt("s", [0, 1, 2, 4, 9, 1e9], 5)}
out["funnel"], out["dist"] = fun, dist

uu = df[df.camp.notna() | df.source.notna()]
d = uu.groupby(observed=True, by=[uu.camp.astype(object).fillna("(none)"), uu.source.astype(object).fillna("(none)"), uu.medium.astype(object).fillna("(none)")]) \
      .agg(n=("pid", "size"), ips=("ip", "nunique"), md=("dur", "median"), first=("date", "min"), last=("date", "max")) \
      .reset_index().sort_values("n", ascending=False).head(40)
out["utm"] = d.values.tolist()

tt = df[df.ch == "TikTok ads"]; ttips = set(tt.ip); tte = tt[tt.step == 0]
out["tiktok"] = {"pings": len(tt), "ips": len(ttips), "md": float(tt.dur.median()) if len(tt) else 0,
                 "bounce": float((ss.loc[tte.sid].n == 1).mean()) if len(tte) else 0, "next_form_ips": len(ttips & formips)}

ent = e.assign(sn=e.sid.map(ss.n), sd=e.sid.map(ss.dur))
out["chq"] = ent[~ent.noise].groupby(observed=True, by="ch").agg(sess=("sid", "size"), pages=("sn", "median"),
             one=("sn", lambda s: (s == 1).mean()), dur=("sd", "median")).reset_index().values.tolist()
vt = df[df.cat == "Virtual tours"].path.astype(str).str.extract(r"^/dal/([^/]+)")[0].value_counts().head(12)
out["tours"] = [[k, int(v)] for k, v in vt.items()]
out["range"] = [df.date.min(), df.date.max()]

def clean(o):
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)): return None
    if isinstance(o, dict): return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [clean(v) for v in o]
    if hasattr(o, "item"): return clean(o.item())
    return o

os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
with open(args.out, "w") as f:
    json.dump(clean(out), f, separators=(",", ":"), default=str)
print(f"Wrote {args.out}: {dq['rows']:,} rows, {out['range'][0]} to {out['range'][1]}")
