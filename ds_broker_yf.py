"""Yahoo Finance (yfinance) provider for NSE equities. REAL market data, but delayed and limited:
1-minute bars exist only for the last ~7 days, so RVOL uses <=5 prior sessions. No option chain, no lot sizes."""
import time, datetime as dt
import pandas as pd
from ds_broker_base import BrokerAdapter, BrokerError

IST = "Asia/Kolkata"
FIELDS = {"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}

class YFinanceBroker(BrokerAdapter):
    name = "YFINANCE"

    def __init__(self, ttl=60):
        self.ttl, self._t, self._days = ttl, 0.0, {}

    def login(self):
        self.state = "AUTHENTICATING"
        try:
            self.prefetch(["RELIANCE"], force=True)
            if not self._days.get("RELIANCE"): raise BrokerError("Yahoo Finance returned no data (blocked or rate-limited?)")
            self.state, self.last_error = "CONNECTED", ""
        except Exception as e:
            self.state, self.last_error = "ERROR", str(e)
            raise BrokerError(str(e)) from e

    def logout(self): self.state = "DISCONNECTED"

    @staticmethod
    def _split(frame: pd.DataFrame) -> list:
        """Raw yahoo 1m frame (one ticker) -> list of per-day DataFrames on a full 09:15-15:29 grid."""
        f = frame.rename(columns=FIELDS)[list(FIELDS.values())].dropna(how="all")
        if f.empty: return []
        idx = f.index
        if idx.tz is None: idx = idx.tz_localize("UTC")
        f.index = idx.tz_convert(IST)
        days = sorted(set(f.index.date)); out = []
        for k, day in enumerate(days):
            d = f[f.index.date == day]
            last = (k == len(days) - 1)
            if len(d) < (2 if last else 300): continue
            grid = pd.date_range(f"{day} 09:15", periods=375, freq="1min", tz=IST)
            if last: grid = grid[grid <= d.index.max()]
            d = d.reindex(grid)
            d[["open", "high", "low", "close"]] = d[["open", "high", "low", "close"]].ffill().bfill()
            d["volume"] = d["volume"].fillna(0)
            out.append(d.rename_axis("ts").reset_index())
        return out

    def prefetch(self, symbols, force=False):
        need = [s for s in symbols if s not in self._days]
        if not force and not need and time.time() - self._t < self.ttl: return
        try:
            import yfinance as yf
        except ImportError as e:
            raise BrokerError("yfinance is not installed (add it to requirements.txt)") from e
        syms = list(dict.fromkeys(symbols))
        try:
            raw = yf.download([s + ".NS" for s in syms], period="7d", interval="1m", group_by="ticker",
                              auto_adjust=False, progress=False, threads=True)
        except Exception as e:
            raise BrokerError(f"Yahoo Finance request failed: {type(e).__name__}") from e
        if raw is None or raw.empty: raise BrokerError("Yahoo Finance returned no data (rate-limited, blocked or market data unavailable)")
        self._days = {}
        for s in syms:
            t = s + ".NS"
            if isinstance(raw.columns, pd.MultiIndex):
                if t not in raw.columns.get_level_values(0): continue
                part = raw[t]
            else:
                part = raw
            self._days[s] = self._split(part)
        self._t = time.time()

    def _get(self, s):
        if s not in self._days: self.prefetch([s])
        d = self._days.get(s)
        if not d: raise BrokerError(f"No Yahoo Finance data for {s}")
        return d

    def get_intraday(self, s): return self._get(s)[-1]
    def get_sessions(self, s, n=20): return self._get(s)[:-1][-n:]
    def get_option_chain(self, s):
        raise BrokerError("Yahoo Finance has no NSE option-chain data. Use Angel One for options.")
