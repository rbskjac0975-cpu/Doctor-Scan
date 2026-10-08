"""Pure analytics: no I/O. Every function uses only data up to the last closed candle."""
from __future__ import annotations
import math
import pandas as pd

SESSION_MIN = 375  # 09:15-15:30
WEIGHTS = dict(rvol=25, momentum=15, candle=10, orb=15, vwap=10,
               liquidity=5, breadth=10, sector=5, timing=5)
assert sum(WEIGHTS.values()) == 100

def clamp(x, lo=0.0, hi=1.0): return max(lo, min(hi, x))

def ticks_to_candles(ticks: pd.DataFrame) -> pd.DataFrame:
    """ticks: ts (tz-aware), ltp, volume (cumulative day volume). Drops duplicates."""
    t = ticks.drop_duplicates(subset=["ts", "ltp", "volume"]).sort_values("ts").copy()
    t["m"] = t["ts"].dt.floor("1min")
    g = t.groupby("m")
    c = g["ltp"].agg(open="first", high="max", low="min", close="last")
    cv = g["volume"].last()
    c["volume"] = cv.diff().fillna(cv).clip(lower=0)
    return c.reset_index().rename(columns={"m": "ts"})

# ---- RVOL (time-normalised) ----
def rvol(cum_now: float, hist_cum_same_minute) -> float | None:
    h = [x for x in hist_cum_same_minute if x and x > 0]
    return cum_now / (sum(h) / len(h)) if h else None

def rvol_class(r) -> str:
    if r is None: return "N/A"
    return "LOW" if r < 1 else "NORMAL" if r < 1.5 else "HIGH" if r < 2 else "VERY HIGH" if r < 3 else "EXTREME"

# ---- VWAP (typical price x volume) ----
def vwap(df: pd.DataFrame) -> float:
    v = df["volume"].sum()
    tp = (df["high"] + df["low"] + df["close"]) / 3
    return float((tp * df["volume"]).sum() / v) if v > 0 else float(df["close"].iloc[-1])

def vwap_trend(df: pd.DataFrame, n=10) -> str:
    if len(df) < n + 2: return "FLAT"
    a, b = vwap(df.iloc[:-n]), vwap(df)
    return "RISING" if b > a * 1.0005 else "FALLING" if b < a * 0.9995 else "FLAT"

# ---- ORB ----
def orb_range(df: pd.DataFrame, minutes: int):
    if len(df) < minutes: return None
    d = df.iloc[:minutes]
    hi, lo = float(d["high"].max()), float(d["low"].min())
    return dict(high=hi, low=lo, mid=(hi + lo) / 2)

def orb_state(df, minutes, rvol_val, vw, min_rvol=1.5, need_vwap=True):
    """Walk closed candles after the range. Returns (state, direction, range). No look-ahead."""
    rng = orb_range(df, minutes)
    if rng is None: return "WATCH", 0, None
    state, d, run, ext = "WATCH", 0, 0, 0.0
    for c in df["close"].iloc[minutes:].tolist():
        up, dn = c > rng["high"], c < rng["low"]
        if state in ("WATCH", "TESTING", "FAILED"):
            if up or dn: state, d, run, ext = "BREAKOUT", (1 if up else -1), 1, c
            elif c >= rng["high"] * 0.999 or c <= rng["low"] * 1.001: state = "TESTING"
            continue
        if not ((d == 1 and up) or (d == -1 and dn)):
            state = "FAILED"; continue
        run += 1
        level = rng["high"] if d == 1 else rng["low"]
        if state == "BREAKOUT":
            ok = (rvol_val or 0) >= min_rvol and (not need_vwap or (df["close"].iloc[-1] - vw) * d > 0)
            if run >= 2 and ok: state = "CONFIRMED"
        elif state in ("CONFIRMED", "CONTINUATION") and abs(c / level - 1) < 0.0015:
            state = "RETEST"
        elif state == "RETEST" and (c - ext) * d > 0:
            state = "CONTINUATION"
        if (c - ext) * d > 0: ext = c
    return state, d, rng

# ---- candle quality / momentum ----
def candle_quality(df: pd.DataFrame, d: int) -> dict:
    r = df.iloc[-1]; rg = r.high - r.low
    if rg <= 0: return dict(body=0, upper=0, lower=0, close_pos=0.5, quality=0.0)
    body = abs(r.close - r.open) / rg
    up_w = (r.high - max(r.open, r.close)) / rg
    lo_w = (min(r.open, r.close) - r.low) / rg
    cp = (r.close - r.low) / rg
    q = .4 * body + .3 * (1 - up_w) + .3 * cp if d >= 0 else .4 * body + .3 * (1 - lo_w) + .3 * (1 - cp)
    return dict(body=body, upper=up_w, lower=lo_w, close_pos=cp, quality=clamp(q))

def atr(df, n=14) -> float:
    pc = df["close"].shift()
    tr = pd.concat([df.high - df.low, (df.high - pc).abs(), (df.low - pc).abs()], axis=1).max(axis=1)
    return float(tr.tail(n).mean())

def returns(df) -> dict:
    c = df["close"]
    def r(n): return float((c.iloc[-1] / c.iloc[-1 - n] - 1) * 100) if len(c) > n else 0.0
    out = {f"r{n}": r(n) for n in (1, 3, 5, 15)}
    out["accel"] = out["r3"] / 3 - out["r15"] / 15
    return out

# ---- market context ----
def breadth(changes) -> dict:
    ch = list(changes)
    adv = sum(c > 0 for c in ch); dec = sum(c < 0 for c in ch); unch = len(ch) - adv - dec
    score = 100 * adv / (adv + dec) if adv + dec else 50.0
    mood = ("VERY BULLISH" if score >= 70 else "BULLISH" if score >= 58 else
            "NEUTRAL" if score >= 42 else "BEARISH" if score >= 30 else "VERY BEARISH")
    n = max(len(ch), 1)
    return dict(advances=adv, declines=dec, unchanged=unch, ad_ratio=adv / max(dec, 1),
                pct_adv=100 * adv / n, pct_dec=100 * dec / n, score=score, mood=mood)

def sector_strength(df: pd.DataFrame) -> pd.DataFrame:
    """df: symbol, sector, change (%)."""
    mkt = df["change"].mean()
    g = df.groupby("sector")["change"]
    out = pd.DataFrame({"return": g.mean(), "breadth": g.apply(lambda s: 100 * (s > 0).mean())})
    out["relative"] = out["return"] - mkt
    out["score"] = 0.5 * out["breadth"] + 0.5 * (50 + out["relative"] * 25).clip(0, 100)
    return out.sort_values("score", ascending=False)

# ---- scoring ----
_ORB_W = dict(CONFIRMED=1, CONTINUATION=.9, RETEST=.7, BREAKOUT=.6, TESTING=.3)

def score_signal(d, rvol_val, r5, cq, orb_st, orb_dir, vwap_aligned, turnover,
                 breadth_score, sector_score, minute) -> dict:
    d = 1 if d >= 0 else -1
    c = dict(
        rvol=clamp((rvol_val or 0) / 3) * WEIGHTS["rvol"],
        momentum=clamp(r5 * d / 1.0) * WEIGHTS["momentum"],
        candle=cq * WEIGHTS["candle"],
        orb=(_ORB_W.get(orb_st, 0) if orb_dir == d else 0) * WEIGHTS["orb"],
        vwap=WEIGHTS["vwap"] if vwap_aligned else 0,
        liquidity=clamp(turnover / 5e8) * WEIGHTS["liquidity"],
        breadth=clamp((breadth_score - 50) / 50 * d) * WEIGHTS["breadth"],
        sector=clamp((sector_score - 50) / 50 * d) * WEIGHTS["sector"],
        timing=WEIGHTS["timing"] if minute <= 60 else 3 if minute <= 180 else 1 if minute <= 345 else 0,
    )
    total = round(sum(c.values()))
    best = max(c, key=lambda k: c[k] / WEIGHTS[k])
    return dict(score=total, components={k: round(v, 1) for k, v in c.items()},
                explanation=f"Scanner score {total}/100; strongest component: {best}.")

def tier(score) -> str:
    return "EXPLOSIVE" if score >= 90 else "STRONG" if score >= 75 else "SPURT" if score >= 60 else "WATCH"

def conviction(score, orb_st, rvol_val, vwap_ok, breadth_ok, sector_ok, liquidity_ok) -> dict:
    """Model-confidence index. NOT a probability of profit."""
    v = (.40 * score / 100 + .20 * _ORB_W.get(orb_st, 0) + .15 * clamp((rvol_val or 0) / 3)
         + .10 * vwap_ok + .08 * breadth_ok + .04 * sector_ok + .03 * liquidity_ok)
    s = round(100 * v)
    return dict(conviction_score=s, conviction_label="LOW" if s < 40 else "MEDIUM" if s < 60 else "HIGH" if s < 80 else "VERY HIGH")

# ---- risk ----
def risk_levels(entry, d, rng=None, vw=None, atr_v=None, model="ORB") -> dict:
    d = 1 if d >= 0 else -1
    stop = None
    if model == "ORB" and rng: stop = rng["low"] if d == 1 else rng["high"]
    elif model == "VWAP" and vw: stop = vw
    if stop is None or (entry - stop) * d <= 0:   # wrong side / unavailable -> ATR fallback
        stop = entry - d * 1.5 * (atr_v or entry * 0.005)
    risk = abs(entry - stop)
    t = [entry + d * k * risk for k in (1, 2, 3)]
    return dict(entry=entry, stop=stop, t1=t[0], t2=t[1], t3=t[2], risk=risk, rr=2.0,
                note="Indicative levels, not guaranteed outcomes.")

def position_size(capital, risk_pct, entry, stop, lot_size=1) -> dict:
    max_risk = capital * risk_pct / 100
    per = abs(entry - stop)
    if per <= 0 or lot_size <= 0: return dict(max_risk=max_risk, quantity=0, lots=0, capital_used=0)
    lots = int(math.floor(max_risk / (per * lot_size)))
    qty = lots * lot_size
    return dict(max_risk=max_risk, quantity=qty, lots=lots, capital_used=qty * entry)

# ---- options ----
def rank_options(chain: list[dict], spot: float, d: int, top=3) -> list[dict]:
    typ = "CE" if d >= 0 else "PE"
    strikes = sorted({x["strike"] for x in chain})
    if not strikes: return []
    atm = min(strikes, key=lambda s: abs(s - spot)); i = strikes.index(atm)
    cand = [x for x in chain if x["type"] == typ and x["ltp"] > 0
            and abs(strikes.index(x["strike"]) - i) <= 2]
    if not cand: return []
    mv = max(x["volume"] for x in cand) or 1; mo = max(x["oi"] for x in cand) or 1
    out = []
    for x in cand:
        sp = (x["ask"] - x["bid"]); sp_pct = 100 * sp / x["ltp"]
        dist = abs(strikes.index(x["strike"]) - i)
        s = .3 * x["volume"] / mv + .3 * x["oi"] / mo + .2 * (1 - clamp(sp_pct / 5)) + .2 * (1 - dist / 2)
        out.append({**x, "spread": sp, "lot_cost": x["ltp"] * x["lot_size"], "rank_score": round(s, 3)})
    return sorted(out, key=lambda r: -r["rank_score"])[:top]
