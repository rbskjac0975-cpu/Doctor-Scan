"""Event-driven ORB backtest. At bar t only candles <= t are visible; entry fills at bar t+1 open."""
import math
import numpy as np, pandas as pd
from . import engine as E

def _day(df, hist_days, orb_min, min_rvol, rr, slip_bps, brok, capital, risk_pct):
    rng = E.orb_range(df, orb_min)
    if rng is None: return None
    for t in range(orb_min, len(df) - 1):
        vis = df.iloc[: t + 1]; c = vis["close"].iloc[-1]
        d = 1 if c > rng["high"] else -1 if c < rng["low"] else 0
        if not d: continue
        rv = E.rvol(vis["volume"].sum(), [h["volume"].cumsum().iloc[t] for h in hist_days if len(h) > t])
        if rv is None or rv < min_rvol or (c - E.vwap(vis)) * d <= 0: continue
        entry = df["open"].iloc[t + 1] * (1 + d * slip_bps / 1e4)
        stop = rng["low"] if d == 1 else rng["high"]
        risk = abs(entry - stop)
        if risk <= 0 or (entry - stop) * d <= 0: continue
        qty = math.floor(capital * risk_pct / 100 / risk)
        if qty < 1: continue
        target, exit_px = entry + d * rr * risk, df["close"].iloc[-1]
        for j in range(t + 1, len(df)):
            lo, hi = df["low"].iloc[j], df["high"].iloc[j]
            if (lo <= stop if d == 1 else hi >= stop): exit_px = stop; break      # stop assumed first (conservative)
            if (hi >= target if d == 1 else lo <= target): exit_px = target; break
        exit_px *= (1 - d * slip_bps / 1e4)
        pnl = (exit_px - entry) * d * qty - 2 * brok
        return dict(entry_time=df["ts"].iloc[t + 1], direction=d, entry=entry, exit=exit_px, qty=qty, pnl=pnl, r=pnl / (qty * risk))
    return None

def metrics(trades: pd.DataFrame) -> dict:
    n = len(trades)
    if n == 0: return dict(trades=0)
    w, l = trades[trades.pnl > 0], trades[trades.pnl <= 0]
    eq = trades.pnl.cumsum()
    return dict(trades=n, net_pnl=trades.pnl.sum(), win_rate=100 * len(w) / n, loss_rate=100 * len(l) / n,
                profit_factor=(w.pnl.sum() / abs(l.pnl.sum())) if len(l) and l.pnl.sum() else float("inf"),
                max_drawdown=float((eq - eq.cummax()).min()), avg_r=trades.r.mean(), expectancy=trades.pnl.mean())

def run_backtest(sessions_by_symbol: dict, orb_min=5, min_rvol=1.5, rr=2.0, slippage_bps=5,
                 brokerage=20.0, capital=100000, risk_pct=1.0, lookback=20):
    rows = []
    for s, days in sessions_by_symbol.items():
        for i in range(1, len(days)):
            r = _day(days[i], days[max(0, i - lookback): i], orb_min, min_rvol, rr, slippage_bps, brokerage, capital, risk_pct)
            if r: rows.append(dict(symbol=s, **r))
    return pd.DataFrame(rows), len(sessions_by_symbol)
