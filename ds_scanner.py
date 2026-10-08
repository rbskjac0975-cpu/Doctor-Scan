import numpy as np, pandas as pd
from ds_broker_base import BrokerError
import ds_engine as E
from ds_universe import SECTOR_OF

def scan(broker, symbols, cfg, upto=None):
    """Returns (rows DataFrame, ctx dict). `upto` truncates to N minutes (mock replay)."""
    data, skipped = {}, {}
    if hasattr(broker, "prefetch"): broker.prefetch(symbols)
    for s in symbols:
        try:
            df = broker.get_intraday(s)
            sess = broker.get_sessions(s, cfg.get("lookback", 20))
        except BrokerError as e:
            skipped[s] = str(e); continue
        if upto: df = df.iloc[:upto]
        if len(df) < 2: continue
        m = len(df)
        hist = [x["volume"].cumsum().iloc[m - 1] for x in sess if len(x) >= m]
        prev_close = float(sess[-1]["close"].iloc[-1]) if sess else float(df["open"].iloc[0])
        data[s] = (df, hist, prev_close)
    if not data:
        raise BrokerError(next(iter(skipped.values()), "No data returned for the selected symbols"))
    chg = {s: (v[0]["close"].iloc[-1] / v[2] - 1) * 100 for s, v in data.items()}
    b = E.breadth(chg.values())
    sec = E.sector_strength(pd.DataFrame({"symbol": list(chg), "sector": [SECTOR_OF.get(s, "OTHER") for s in chg],
                                          "change": list(chg.values())}))
    rows = []
    for s, (df, hist, pc) in data.items():
        m, price = len(df), float(df["close"].iloc[-1])
        vw = E.vwap(df); cum = float(df["volume"].sum()); rv = E.rvol(cum, hist)
        st, od, rng = E.orb_state(df, cfg["orb_min"], rv, vw, cfg["min_rvol"])
        d = od if od and st not in ("FAILED", "WATCH", "TESTING") else (1 if price >= vw else -1)
        cq = E.candle_quality(df, d); ret = E.returns(df); turnover = cum * price
        sector = SECTOR_OF.get(s, "OTHER"); ss = float(sec.loc[sector, "score"]) if sector in sec.index else 50
        aligned = (price - vw) * d > 0
        sc = E.score_signal(d, rv, ret["r5"], cq["quality"], st, od, aligned, turnover, b["score"], ss, m)
        cv = E.conviction(sc["score"], st, rv, aligned, (b["score"] - 50) * d > 0, (ss - 50) * d > 0, turnover >= cfg["min_turnover"])
        reasons = []
        if rv is None or rv < cfg["min_rvol"]: reasons.append("low RVOL")
        if turnover < cfg["min_turnover"] or price < cfg["min_price"]: reasons.append("poor liquidity")
        if cq["quality"] < 0.35: reasons.append("weak candle")
        if st == "FAILED": reasons.append("failed breakout")
        if (b["score"] - 50) * d < -30: reasons.append("against market trend")
        tr = E.tier(sc["score"]) if not reasons else "WATCH"
        rows.append(dict(symbol=s, sector=sector, ltp=price, change=chg[s], volume=cum, rvol=rv, rvol_class=E.rvol_class(rv),
                         orb=st, vwap=vw, vwap_side="ABOVE" if price >= vw else "BELOW", vwap_dist=(price / vw - 1) * 100,
                         score=sc["score"], tier=tr, direction="BULLISH" if d > 0 else "BEARISH", d=d,
                         conviction=cv["conviction_score"], conviction_label=cv["conviction_label"],
                         explanation=sc["explanation"], components=sc["components"], reject="; ".join(reasons),
                         time=df["ts"].iloc[-1].strftime("%H:%M"), orb_high=rng and rng["high"], orb_low=rng and rng["low"],
                         atr=E.atr(df), turnover=turnover, lot=broker.lot_size(s)))
    out = pd.DataFrame(rows)
    return out, dict(breadth=b, sectors=sec, candles={s: v[0] for s, v in data.items()}, skipped=skipped, n_sessions=min((len(v[1]) for v in data.values()), default=0))

def attach_options(broker, df):
    """Best-ranked contract for actionable signals (mock chain, or live if implemented)."""
    opt, ltp, cost = [], [], []
    for r in df.itertuples():
        pick = None
        if r.tier != "WATCH":
            try: pick = (E.rank_options(broker.get_option_chain(r.symbol), r.ltp, r.d, 1) or [None])[0]
            except Exception: pick = None
        opt.append(f"{r.symbol} {int(pick['strike'])} {pick['type']}" if pick else "")
        ltp.append(pick["ltp"] if pick else None); cost.append(pick["lot_cost"] if pick else None)
    return df.assign(option=opt, option_ltp=ltp, lot_cost=cost)
