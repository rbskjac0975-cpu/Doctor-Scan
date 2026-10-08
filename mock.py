"""Synthetic data generator. Everything here is SIMULATED and must be labelled MOCK DATA."""
import zlib, datetime as dt
import numpy as np, pandas as pd
from .base import BrokerAdapter

IST = "Asia/Kolkata"
def _seed(*a): return zlib.crc32("|".join(map(str, a)).encode())
def last_weekday(d):
    while d.weekday() >= 5: d -= dt.timedelta(days=1)
    return d
def prev_weekday(d): return last_weekday(d - dt.timedelta(days=1))

class MockBroker(BrokerAdapter):
    name, is_mock = "MOCK", True

    def __init__(self): self.state = "CONNECTED"
    def login(self): self.state = "CONNECTED"
    def logout(self): self.state = "DISCONNECTED"
    def get_profile(self): return {"name": "MOCK USER", "note": "simulated"}

    def lot_size(self, s): return [250, 500, 750, 1000, 1500, 2000][_seed("lot", s) % 6]
    def base_price(self, s): return 100 + _seed("px", s) % 4000

    def _day(self, s, day, hot=False):
        rng = np.random.default_rng(_seed(s, day))
        m = np.arange(SESSION := 375)
        drift = np.where(m > 8, 0.0007, 0.0) if hot else 0.0
        ret = rng.normal(0, 0.0007, SESSION) + drift
        p0 = self.base_price(s) * (1 + rng.normal(0, 0.01))
        close = p0 * np.exp(np.cumsum(ret))
        open_ = np.r_[p0, close[:-1]]
        wick = np.abs(rng.normal(0, 0.0004, (2, SESSION)))
        high = np.maximum(open_, close) * (1 + wick[0]); low = np.minimum(open_, close) * (1 - wick[1])
        prof = 1 + 1.5 * np.exp(-m / 30) + 1.2 * np.exp(-(SESSION - m) / 30)
        base = (_seed("v", s) % 50 + 10) * 400
        vol = base * prof * rng.lognormal(0, 0.3, SESSION) * (np.where(m > 8, 2.8, 1) if hot else 1)
        ts = pd.date_range(f"{day} 09:15", periods=SESSION, freq="1min", tz=IST)
        return pd.DataFrame(dict(ts=ts, open=open_, high=high, low=low, close=close, volume=vol.round()))

    def _today(self): return last_weekday(dt.datetime.now().date())
    def is_hot(self, s): return _seed("hot", s) % 5 == 0

    def get_intraday(self, s): return self._day(s, self._today(), self.is_hot(s))
    def get_sessions(self, s, n=20):
        d, out = prev_weekday(self._today()), []
        for _ in range(n):
            out.append(self._day(s, d)); d = prev_weekday(d)
        return out[::-1]

    def get_option_chain(self, s):
        spot = float(self.get_intraday(s)["close"].iloc[-1]); lot = self.lot_size(s)
        step = max(5, round(spot * 0.01 / 5) * 5); atm = round(spot / step) * step
        rng = np.random.default_rng(_seed("oc", s)); exp = str(self._today() + dt.timedelta(days=(3 - self._today().weekday()) % 7 + 21))
        rows = []
        for k in range(-5, 6):
            K = atm + k * step
            for t in ("CE", "PE"):
                intrinsic = max(spot - K, 0) if t == "CE" else max(K - spot, 0)
                ltp = round(intrinsic + spot * 0.012 * np.exp(-abs(k) / 3), 2)
                sp = round(ltp * rng.uniform(0.004, 0.03), 2)
                rows.append(dict(strike=K, type=t, expiry=exp, ltp=ltp, bid=round(ltp - sp / 2, 2), ask=round(ltp + sp / 2, 2),
                                 volume=int(rng.integers(100, 50000) * np.exp(-abs(k) / 3)), oi=int(rng.integers(5e3, 5e5) * np.exp(-abs(k) / 4)),
                                 oi_chg=int(rng.integers(-5e4, 8e4)), iv=round(rng.uniform(14, 32), 1), lot_size=lot))
        return rows
