import datetime as dt, requests
from ds_config import TG_TOKEN, TG_CHAT, DISCLAIMER

def diff(prev: dict, df):
    """prev: {symbol: (score, orb, rvol)}. Returns (events, new_prev)."""
    ev, new = [], {}
    now = dt.datetime.now().strftime("%H:%M")
    for r in df.itertuples():
        new[r.symbol] = (r.score, r.orb, r.rvol or 0)
        if r.symbol not in prev: continue
        ps, po, pr = prev[r.symbol]
        if r.orb == "CONFIRMED" and po != "CONFIRMED": ev.append((now, "BREAKOUT CONFIRMED", r.symbol, f"{r.direction} score {r.score}"))
        if r.orb == "FAILED" and po != "FAILED": ev.append((now, "FAILED BREAKOUT", r.symbol, ""))
        if (r.rvol or 0) >= 2 > pr: ev.append((now, "RVOL SPIKE", r.symbol, f"RVOL crossed 2.0x ({r.rvol:.1f}x)"))
        if r.score - ps >= 8: ev.append((now, "SCORE UPGRADE", r.symbol, f"{ps} -> {r.score}"))
        if ps - r.score >= 8: ev.append((now, "SCORE DOWNGRADE", r.symbol, f"{ps} -> {r.score}"))
        if r.tier in ("EXPLOSIVE", "STRONG") and ps < 75: ev.append((now, "NEW LEADER", r.symbol, f"{r.tier} {r.score}"))
    return ev, new

def telegram(text):
    if not (TG_TOKEN and TG_CHAT): return False, "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set"
    try:
        r = requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                          json={"chat_id": TG_CHAT, "text": f"{text}\n\n{DISCLAIMER}"}, timeout=10)
        return r.ok, "sent" if r.ok else f"Telegram error {r.status_code}"
    except requests.RequestException as e:
        return False, f"Telegram unreachable: {type(e).__name__}"
