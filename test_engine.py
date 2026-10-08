import numpy as np, pandas as pd, pytest
from doctorscan import engine as E, backtest
from doctorscan.brokers.mock import MockBroker
from doctorscan.brokers.angel_one import AngelOneBroker
from doctorscan.brokers.base import BrokerError

def mk(closes, vol=100, spread=0.2):
    c = np.array(closes, float)
    return pd.DataFrame(dict(open=np.r_[c[0], c[:-1]], high=c + spread, low=c - spread, close=c, volume=vol,
                             ts=pd.date_range("2026-10-08 09:15", periods=len(c), freq="1min", tz="Asia/Kolkata")))

def test_rvol_time_normalised():
    assert E.rvol(300, [100, 200, 300]) == pytest.approx(1.5)
    assert E.rvol(1, []) is None
    assert [E.rvol_class(x) for x in (.5, 1.2, 1.7, 2.5, 3.5)] == ["LOW", "NORMAL", "HIGH", "VERY HIGH", "EXTREME"]

def test_vwap():
    df = pd.DataFrame(dict(high=[10, 20], low=[10, 20], close=[10, 20], volume=[1, 3]))
    assert E.vwap(df) == pytest.approx(17.5)

def test_orb_range_and_states():
    base = [100] * 5
    df = mk(base + [101, 101.5, 102, 102.1], spread=0.1)
    st, d, rng = E.orb_state(df, 5, 2.0, 100.5)
    assert rng["high"] == pytest.approx(100.1) and (st, d) == ("CONFIRMED", 1)
    assert E.orb_state(df, 5, 0.5, 100.5)[0] == "BREAKOUT"           # RVOL gate blocks confirmation
    fail = mk(base + [101, 100], spread=0.1)
    assert E.orb_state(fail, 5, 2.0, 100)[0] == "FAILED"
    assert E.orb_state(mk(base[:3]), 5, 2, 100)[0] == "WATCH"        # range incomplete

def test_no_lookahead_orb():
    df = mk([100] * 5 + [101, 102, 103])
    a = E.orb_state(df.iloc[:6], 5, 2, 100)[0]
    assert a == "BREAKOUT"                                            # later candles don't change the earlier state

def test_candle_quality():
    bull = pd.DataFrame(dict(open=[100], high=[101.05], low=[99.95], close=[101.0]))
    bear_view = E.candle_quality(bull, -1)["quality"]
    assert E.candle_quality(bull, 1)["quality"] > .8 > bear_view

def test_score_weights_and_tiers():
    assert sum(E.WEIGHTS.values()) == 100
    s = E.score_signal(1, 3, 1, 1, "CONFIRMED", 1, True, 5e8, 100, 100, 10)
    assert s["score"] == 100 and E.tier(100) == "EXPLOSIVE"
    assert [E.tier(x) for x in (89, 75, 60, 59)] == ["STRONG", "STRONG", "SPURT", "WATCH"]
    assert E.score_signal(1, 0, 0, 0, "WATCH", 0, False, 0, 0, 0, 400)["score"] == 0

def test_conviction_label():
    assert E.conviction(95, "CONFIRMED", 3, 1, 1, 1, 1)["conviction_label"] == "VERY HIGH"
    assert E.conviction(10, "WATCH", 0, 0, 0, 0, 0)["conviction_label"] == "LOW"

def test_breadth_and_sector():
    b = E.breadth([1] * 128 + [-1] * 71 + [0] * 6)
    assert (b["advances"], b["declines"], b["unchanged"]) == (128, 71, 6)
    assert b["ad_ratio"] == pytest.approx(128 / 71)
    assert E.breadth([-1] * 10)["mood"] == "VERY BEARISH"
    s = E.sector_strength(pd.DataFrame(dict(symbol="a b c".split(), sector=["X", "X", "Y"], change=[2, 1, -1])))
    assert s.index[0] == "X" and s.loc["X", "relative"] > 0

def test_risk_and_sizing():
    r = E.risk_levels(100, 1, rng=dict(high=101, low=98, mid=99.5))
    assert (r["stop"], r["t2"], r["rr"]) == (98, 104, 2.0)
    short = E.risk_levels(100, -1, rng=dict(high=102, low=99, mid=100))
    assert short["stop"] == 102 and short["t1"] == 98
    p = E.position_size(100000, 1, 100, 98, lot_size=1)
    assert p["max_risk"] == 1000 and p["quantity"] == 500
    q = E.position_size(100000, 1, 100, 98, lot_size=600)           # 1 lot risks 1200 > 1000 -> 0 lots
    assert q["quantity"] == 0 and E.position_size(500000, 1, 100, 98, 300)["quantity"] % 300 == 0

def test_option_ranking():
    ch = [dict(strike=k, type=t, ltp=10, bid=9.9, ask=10.1, volume=100 * (5 - abs(k - 100)), oi=1000, lot_size=50, expiry="x")
          for k in range(94, 107) for t in ("CE", "PE")]
    top = E.rank_options(ch, 100.2, 1)
    assert top[0]["type"] == "CE" and top[0]["strike"] == 100 and top[0]["lot_cost"] == 500

def test_candle_aggregation_dedup():
    t = pd.DataFrame(dict(ts=pd.to_datetime(["2026-10-08 09:15:05", "2026-10-08 09:15:05", "2026-10-08 09:15:40", "2026-10-08 09:16:10"]).tz_localize("Asia/Kolkata"),
                          ltp=[100, 100, 101, 99], volume=[10, 10, 30, 70]))
    c = E.ticks_to_candles(t)
    assert len(c) == 2 and c.volume.tolist() == [30, 40] and c.high[0] == 101

def test_mock_pipeline_and_backtest():
    b = MockBroker(); assert b.is_mock
    sess = {s: b.get_sessions(s, 6) for s in ("TCS", "BEL")}
    t, n = backtest.run_backtest(sess, min_rvol=0.5)
    m = backtest.metrics(t)
    assert m["trades"] == 0 or {"win_rate", "profit_factor", "max_drawdown", "expectancy"} <= set(m)

class FakeSmart:
    def __init__(self, api_key): pass
    def generateSession(self, c, p, t): return {"status": True, "data": {"refreshToken": "r"}}
    def getfeedToken(self): return "f"
    def terminateSession(self, c): return {}

def test_angel_login_mocked(monkeypatch):
    for k, v in dict(ANGEL_ONE_API_KEY="k", ANGEL_ONE_CLIENT_CODE="c", ANGEL_ONE_PASSWORD="p", ANGEL_ONE_TOTP="JBSWY3DPEHPK3PXP").items():
        monkeypatch.setenv(k, v)
    a = AngelOneBroker(smart_factory=FakeSmart); a.login()
    assert a.state == "CONNECTED" and a.feed_token == "f"

def test_angel_requires_connection_and_creds(monkeypatch):
    with pytest.raises(BrokerError): AngelOneBroker().get_quote("TCS")
    monkeypatch.delenv("ANGEL_ONE_API_KEY", raising=False)
    a = AngelOneBroker(smart_factory=FakeSmart)
    with pytest.raises(BrokerError): a.login()
    assert a.state == "ERROR"
