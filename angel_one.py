"""Angel One SmartAPI adapter (REST). Uses only documented smartapi-python calls:
SmartConnect.generateSession / getfeedToken / getProfile / getCandleData / ltpData /
orderBook / position / terminateSession, and the public OpenAPIScripMaster.json."""
import os, json, time, logging, datetime as dt
import pandas as pd, requests
from .base import BrokerAdapter, BrokerError
from .mock import last_weekday, prev_weekday

log = logging.getLogger("doctorscan.angel")
MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
IST = "Asia/Kolkata"

class AngelOneBroker(BrokerAdapter):
    name = "ANGEL_ONE"

    def __init__(self, smart_factory=None, cache="instruments.json"):
        self._factory, self._cache = smart_factory, cache
        self.api = None; self.feed_token = None; self.refresh_token = None
        self._inst = None; self._tok = {}; self._lots = {}

    def _env(self, k):
        v = os.getenv(k, "")
        if not v: raise BrokerError(f"Missing environment variable {k}")
        return v

    def login(self):
        self.state = "AUTHENTICATING"
        try:
            import pyotp
            factory = self._factory
            if factory is None:
                from SmartApi import SmartConnect as factory
            self.api = factory(api_key=self._env("ANGEL_ONE_API_KEY"))
            code = pyotp.TOTP(self._env("ANGEL_ONE_TOTP")).now()
            r = self.api.generateSession(self._env("ANGEL_ONE_CLIENT_CODE"), self._env("ANGEL_ONE_PASSWORD"), code)
            if not r or not r.get("status"):
                raise BrokerError(f"Angel One login failed: {(r or {}).get('message', 'no response')}")
            self.refresh_token = r["data"]["refreshToken"]
            self.feed_token = self.api.getfeedToken()
            self.state = "CONNECTED"; self.last_error = ""
            log.info("angel_one login ok")   # never log secrets/tokens
        except Exception as e:
            self.state, self.last_error = "ERROR", str(e)
            raise BrokerError(str(e)) from e

    def logout(self):
        try:
            if self.api: self.api.terminateSession(self._env("ANGEL_ONE_CLIENT_CODE"))
        finally:
            self.state = "DISCONNECTED"; self.api = None

    def _need(self):
        if self.state != "CONNECTED" or not self.api: raise BrokerError("Angel One is not connected. Login first.")

    def get_profile(self): self._need(); return self.api.getProfile(self.refresh_token)

    def get_instruments(self):
        if self._inst is None:
            if os.path.exists(self._cache) and time.time() - os.path.getmtime(self._cache) < 86400:
                self._inst = json.load(open(self._cache))
            else:
                r = requests.get(MASTER_URL, timeout=60); r.raise_for_status()
                self._inst = r.json(); json.dump(self._inst, open(self._cache, "w"))
            for x in self._inst:
                if x.get("exch_seg") == "NSE" and x.get("symbol", "").endswith("-EQ"):
                    self._tok[x["name"]] = (x["token"], x["symbol"])
                elif x.get("exch_seg") == "NFO" and x.get("instrumenttype") == "FUTSTK":
                    self._lots.setdefault(x["name"], int(x["lotsize"]))   # lot size from master, never hard-coded
        return self._inst

    def _token(self, s):
        self.get_instruments()
        if s not in self._tok: raise BrokerError(f"Symbol {s} not found in instrument master")
        return self._tok[s]

    def lot_size(self, s): self.get_instruments(); return self._lots.get(s, 1)

    def get_quote(self, s):
        self._need(); tok, ts = self._token(s)
        r = self.api.ltpData("NSE", ts, tok)
        if not r.get("status"): raise BrokerError(r.get("message", "ltpData failed"))
        return r["data"]

    def _candles(self, s, frm, to):
        self._need(); tok, _ = self._token(s)
        r = self.api.getCandleData({"exchange": "NSE", "symboltoken": tok, "interval": "ONE_MINUTE",
                                    "fromdate": frm.strftime("%Y-%m-%d %H:%M"), "todate": to.strftime("%Y-%m-%d %H:%M")})
        if not r or not r.get("status"): raise BrokerError(f"getCandleData failed: {(r or {}).get('message', '')} (rate limit?)")
        df = pd.DataFrame(r["data"] or [], columns=["ts", "open", "high", "low", "close", "volume"])
        if df.empty: return df
        df["ts"] = pd.to_datetime(df["ts"]).dt.tz_convert(IST) if pd.to_datetime(df["ts"]).dt.tz is not None else pd.to_datetime(df["ts"]).dt.tz_localize(IST)
        return df

    def get_intraday(self, s):
        day = last_weekday(dt.datetime.now().date())     # NOTE: exchange holidays are not modelled
        end = min(dt.datetime.now(), dt.datetime.combine(day, dt.time(15, 30))) if day == dt.datetime.now().date() else dt.datetime.combine(day, dt.time(15, 30))
        df = self._candles(s, dt.datetime.combine(day, dt.time(9, 15)), end)
        if df.empty: raise BrokerError(f"No intraday candles for {s}")
        return df

    def get_sessions(self, s, n=20):
        today = last_weekday(dt.datetime.now().date())
        frm = dt.datetime.combine(today - dt.timedelta(days=29), dt.time(9, 15))   # 1-min history limited per request
        df = self._candles(s, frm, dt.datetime.combine(prev_weekday(today), dt.time(15, 30)))
        time.sleep(0.4)  # stay under SmartAPI per-second limits
        if df.empty: return []
        days = [g.reset_index(drop=True) for _, g in df.groupby(df["ts"].dt.date)]
        return [d for d in days if len(d) >= 300][-n:]

    def get_order_book(self): self._need(); return self.api.orderBook()
    def get_positions(self): self._need(); return self.api.position()
    def websocket_connect(self):
        raise NotImplementedError("SmartWebSocketV2 needs a long-running worker; this Streamlit build polls REST.")
    def get_option_chain(self, s):
        raise BrokerError("Live option chain is not implemented in this build (needs per-contract quotes from NFO instruments).")
