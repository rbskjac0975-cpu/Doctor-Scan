import time, datetime as dt
import pandas as pd, streamlit as st, plotly.graph_objects as go
import ds_config as config, ds_engine as E, ds_scanner as scanner, ds_backtest as backtest, ds_db as db, ds_alerts as alerts
from ds_broker_base import BrokerError
from ds_broker_mock import MockBroker
from ds_broker_angel import AngelOneBroker
from ds_broker_yf import YFinanceBroker
from ds_universe import SYMBOLS

st.set_page_config("DOCTOR SCAN", "🩺", layout="wide")
st.markdown("""<style>.stApp{background:#0b0f17}[data-testid=stSidebar]{background:#0e1420}
.pill{padding:2px 10px;border-radius:12px;font-size:12px;font-weight:600}
.mock{background:#5a3d00;color:#ffc857}.live{background:#0d3b24;color:#3ddc84}.dead{background:#4a1515;color:#ff6b6b}
.card{border:1px solid #243049;border-radius:10px;padding:10px 12px;margin-bottom:8px;background:#111827}
.up{color:#3ddc84}.dn{color:#ff6b6b}.mono{font-family:ui-monospace,monospace}</style>""", unsafe_allow_html=True)

@st.cache_resource
def get_broker():
    return {"ANGEL_ONE": AngelOneBroker, "MOCK": MockBroker}.get(config.PROVIDER, YFinanceBroker)()
broker = get_broker()
ss = st.session_state
ss.setdefault("prev", {}); ss.setdefault("alerts", [])

# ---------- sidebar ----------
PAGES = ["Dashboard", "Live Scanner", "Breakout Leaders", "Market Breadth", "Sectors", "Options", "Stock Detail",
         "Alerts", "History", "Analytics", "Backtest", "Risk Calculator"]
page = st.sidebar.radio("DOCTOR SCAN", PAGES)
cfg = dict(orb_min=st.sidebar.selectbox("ORB period (min)", [5, 15, 30]),
           min_rvol=st.sidebar.slider("Min RVOL", 0.5, 3.0, 1.5, 0.1),
           min_score=st.sidebar.slider("Min score", 0, 90, 60),
           min_turnover=st.sidebar.number_input("Min turnover (₹ Cr)", 0.0, 500.0, 5.0) * 1e7,
           min_price=st.sidebar.number_input("Min price (₹)", 0.0, 5000.0, 50.0), lookback=20)
universe = st.sidebar.multiselect("Universe", SYMBOLS, SYMBOLS if broker.is_mock else SYMBOLS[:15])
upto = st.sidebar.slider("Simulated minute (MOCK replay)", 15, 375, 375) if broker.is_mock else None
auto = st.sidebar.checkbox("Auto-refresh (30s)", False)

# ---------- header + provider status (never silently falls back) ----------
now = dt.datetime.now(dt.timezone(dt.timedelta(hours=5, minutes=30)))
open_ = now.weekday() < 5 and dt.time(9, 15) <= now.time() <= dt.time(15, 30)
c1, c2 = st.columns([3, 2])
c1.markdown(f"### 🩺 DOCTOR SCAN &nbsp; <span class='mono'>{now:%H:%M:%S} IST</span>", unsafe_allow_html=True)
if broker.is_mock:
    c2.markdown("<span class='pill mock'>⚠ MOCK DATA — simulated, not exchange data</span>", unsafe_allow_html=True)
elif broker.name == "YFINANCE":
    if broker.state != "CONNECTED":
        try: broker.login()
        except BrokerError: pass
    ok_ = broker.state == "CONNECTED"
    c2.markdown(f"<span class='pill {'live' if ok_ else 'dead'}'>{'YAHOO FINANCE · REAL NSE DATA, DELAYED' if ok_ else 'YAHOO FINANCE UNAVAILABLE'}</span>", unsafe_allow_html=True)
    if not ok_: st.error(broker.last_error or "Could not fetch data from Yahoo Finance."); st.stop()
    st.caption("Yahoo's NSE 1-minute data is delayed (typically ~15 min) and limited to ~7 days, so RVOL uses only the prior sessions available (≤5), not 20.")
else:
    with st.sidebar.expander("Angel One session", expanded=broker.state != "CONNECTED"):
        st.caption(f"State: {broker.state}")
        if st.button("Login"):
            try: broker.login()
            except BrokerError as e: st.error(str(e))
        if st.button("Logout"): broker.logout()
    cls, txt = ("live", "ANGEL ONE LIVE") if broker.state == "CONNECTED" else ("dead", "ANGEL ONE DISCONNECTED")
    c2.markdown(f"<span class='pill {cls}'>{txt}</span>", unsafe_allow_html=True)
    if broker.state != "CONNECTED":
        st.error(broker.last_error or "Not connected. Use Login in the sidebar. No data is shown without a valid broker session.")
        st.stop()
if not open_: st.info("MARKET CLOSED — showing last session data")
st.caption(config.DISCLAIMER)

@st.cache_data(ttl=30, show_spinner="Scanning…")
def run(_b, key, syms, cfg_t, upto):
    df, ctx = scanner.scan(_b, list(syms), dict(cfg_t), upto)
    return scanner.attach_options(_b, df), ctx
try:
    df, ctx = run(broker, broker.name, tuple(universe), tuple(sorted(cfg.items())), upto)
except BrokerError as e:
    st.error(f"Data error: {e}"); st.stop()
if df.empty: st.warning("No data for the selected universe."); st.stop()

ev, ss["prev"] = alerts.diff(ss["prev"], df)
ss["alerts"] = (ev + ss["alerts"])[:200]
sigs = df[(df.tier != "WATCH") & (df.score >= cfg["min_score"])]
for r in sigs.to_dict("records"):
    rk = E.risk_levels(r["ltp"], r["d"], dict(high=r["orb_high"], low=r["orb_low"]) if r["orb_high"] else None, r["vwap"], r["atr"])
    db.save(r, rk, "MOCK" if broker.is_mock else "LIVE")
db.update_status(dict(zip(df.symbol, df.ltp)))
b = ctx["breadth"]

def fmt(d):
    d = d.copy(); d["rvol"] = d["rvol"].round(2); d["ltp"] = d["ltp"].round(2); d["change"] = d["change"].round(2)
    return d

COLS = ["symbol", "ltp", "change", "volume", "rvol", "orb", "vwap_side", "score", "tier", "direction", "option", "time"]
def card(r):
    cls = "up" if r["change"] >= 0 else "dn"
    opt = f"{r['option']} @ ₹{r['option_ltp']:.1f} (lot ₹{r['lot_cost']:,.0f})" if r["option"] else "—"
    st.markdown(f"""<div class='card'><b>{r['symbol']}</b> <span class='{cls} mono'>₹{r['ltp']:,.2f} ({r['change']:+.2f}%)</span><br>
    <span class='mono'>RVOL {r['rvol']:.2f}x · Score {r['score']} · {r['direction']}</span><br>
    ORB: {r['orb']} · VWAP: {r['vwap_side']}<br>Option: {opt}<br>
    Model conviction: {r['conviction']} ({r['conviction_label']}) · {r['time']}</div>""", unsafe_allow_html=True)

# ---------- pages ----------
if page == "Dashboard":
    m = st.columns(5)
    m[0].metric("Market mood", b["mood"]); m[1].metric("Advances", b["advances"]); m[2].metric("Declines", b["declines"])
    m[3].metric("A/D ratio", f"{b['ad_ratio']:.2f}"); m[4].metric("Signals", len(sigs))
    a, c, d = st.columns(3)
    a.subheader("Top breakouts"); a.dataframe(fmt(sigs.sort_values("score", ascending=False))[["symbol", "score", "tier", "orb"]].head(8), hide_index=True)
    c.subheader("Top gainers"); c.dataframe(fmt(df.nlargest(8, "change"))[["symbol", "ltp", "change"]], hide_index=True)
    d.subheader("Top losers"); d.dataframe(fmt(df.nsmallest(8, "change"))[["symbol", "ltp", "change"]], hide_index=True)
    a, c, d = st.columns(3)
    a.subheader("Highest RVOL"); a.dataframe(fmt(df.nlargest(8, "rvol"))[["symbol", "rvol", "rvol_class"]], hide_index=True)
    sec = ctx["sectors"]; c.subheader("Strongest sectors"); c.dataframe(sec.head(4).round(2))
    d.subheader("Weakest sectors"); d.dataframe(sec.tail(4).round(2))
    st.subheader("Live alerts"); st.dataframe(pd.DataFrame(ss["alerts"][:10], columns=["time", "event", "symbol", "detail"]), hide_index=True)
    st.caption(f"Scanner health: {broker.name} · state {broker.state} · {len(df)} symbols scanned · RVOL baseline sessions: {ctx['n_sessions']}" + (f" · skipped: {', '.join(ctx['skipped'])}" if ctx["skipped"] else ""))

elif page == "Live Scanner":
    f = st.radio("Filter", ["All", "Bullish", "Bearish", "Explosive", "Strong", "Spurt", "High RVOL", "ORB Breakout", "Above VWAP", "Below VWAP"], horizontal=True)
    q = st.text_input("Search symbol").upper()
    v = df
    v = {"Bullish": v[v.d > 0], "Bearish": v[v.d < 0], "Explosive": v[v.tier == "EXPLOSIVE"], "Strong": v[v.tier == "STRONG"],
         "Spurt": v[v.tier == "SPURT"], "High RVOL": v[v.rvol >= 1.5], "ORB Breakout": v[v.orb.isin(["BREAKOUT", "CONFIRMED", "RETEST", "CONTINUATION"])],
         "Above VWAP": v[v.vwap_side == "ABOVE"], "Below VWAP": v[v.vwap_side == "BELOW"]}.get(f, v)
    if q: v = v[v.symbol.str.contains(q)]
    st.dataframe(fmt(v.sort_values("score", ascending=False))[COLS], hide_index=True, use_container_width=True)  # click headers to sort
    st.caption("Rejected signals show reasons in Stock Detail. Scores are model outputs, not predictions.")

elif page == "Breakout Leaders":
    for t, col in zip(["EXPLOSIVE", "STRONG", "SPURT"], st.columns(3)):
        col.subheader(t)
        sub = sigs[sigs.tier == t].sort_values("score", ascending=False).head(6)
        if sub.empty: col.caption("None right now")
        for r in sub.to_dict("records"):
            with col: card(r)

elif page == "Market Breadth":
    st.metric("Mood", b["mood"], f"breadth score {b['score']:.0f}/100")
    st.write(f"Advances **{b['advances']}** · Declines **{b['declines']}** · Unchanged **{b['unchanged']}** · A/D **{b['ad_ratio']:.2f}** · "
             f"{b['pct_adv']:.0f}% advancing / {b['pct_dec']:.0f}% declining")
    st.bar_chart(pd.Series(dict(Advances=b["advances"], Declines=b["declines"], Unchanged=b["unchanged"])))

elif page == "Sectors":
    st.dataframe(ctx["sectors"].round(2), use_container_width=True); st.bar_chart(ctx["sectors"]["score"])

elif page == "Options":
    s = st.selectbox("Symbol", df.symbol)
    try:
        ch = broker.get_option_chain(s); cdf = pd.DataFrame(ch)
        ce, pe = cdf[cdf.type == "CE"].set_index("strike"), cdf[cdf.type == "PE"].set_index("strike")
        t = pd.DataFrame({"CALL OI": ce.oi, "CALL ΔOI": ce.oi_chg, "CALL VOL": ce.volume, "CALL IV": ce.iv, "CALL LTP": ce.ltp,
                          "PUT LTP": pe.ltp, "PUT IV": pe.iv, "PUT VOL": pe.volume, "PUT ΔOI": pe.oi_chg, "PUT OI": pe.oi})
        spot = float(df.set_index("symbol").loc[s, "ltp"]); atm = min(t.index, key=lambda k: abs(k - spot))
        st.write(f"Spot ₹{spot:,.2f} · ATM **{atm}** · PCR (OI) **{pe.oi.sum() / max(ce.oi.sum(), 1):.2f}** · max call OI {ce.oi.idxmax()} · max put OI {pe.oi.idxmax()}")
        st.dataframe(t.style.apply(lambda r: ["background:#1d2b4a" if r.name == atm else "" for _ in r], axis=1), use_container_width=True)
        d = int(df.set_index("symbol").loc[s, "d"]); st.subheader("Ranked candidates"); st.dataframe(pd.DataFrame(E.rank_options(ch, spot, d)))
    except (BrokerError, NotImplementedError) as e: st.warning(str(e))

elif page == "Stock Detail":
    s = st.selectbox("Symbol", df.symbol); r = df.set_index("symbol").loc[s]; c = ctx["candles"][s]
    m = st.columns(5); m[0].metric("LTP", f"₹{r.ltp:,.2f}", f"{r.change:+.2f}%"); m[1].metric("RVOL", f"{r.rvol:.2f}x", r.rvol_class)
    m[2].metric("Score", f"{r.score}", r.tier); m[3].metric("Conviction*", r.conviction, r.conviction_label); m[4].metric("ORB", r.orb)
    fig = go.Figure(go.Candlestick(x=c.ts, open=c.open, high=c.high, low=c.low, close=c.close, name="1m"))
    fig.add_hline(y=r.orb_high, line_dash="dot", annotation_text="ORB high"); fig.add_hline(y=r.orb_low, line_dash="dot", annotation_text="ORB low")
    fig.add_hline(y=r.vwap, line_color="orange", annotation_text="VWAP")
    fig.update_layout(template="plotly_dark", height=450, xaxis_rangeslider_visible=False, margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig, use_container_width=True)
    a, bb = st.columns(2)
    a.subheader("Score breakdown"); a.bar_chart(pd.Series(r.components)); a.caption(r.explanation + (f" Filtered: {r.reject}" if r.reject else ""))
    rk = E.risk_levels(r.ltp, int(r.d), dict(high=r.orb_high, low=r.orb_low), r.vwap, r.atr)
    bb.subheader("Indicative risk levels"); bb.json({k: round(v, 2) if isinstance(v, float) else v for k, v in rk.items()})
    st.caption("*Conviction is a model-confidence index, not a probability of profit. Levels are indicative, not guaranteed.")

elif page == "Alerts":
    if st.button("Send test alert to Telegram"):
        ok, msg = alerts.telegram("TEST ALERT — DOCTOR SCAN"); (st.success if ok else st.error)(msg)
    st.dataframe(pd.DataFrame(ss["alerts"], columns=["time", "event", "symbol", "detail"]), hide_index=True, use_container_width=True)
    st.caption("Alerts are generated when the scan refreshes (diff against the previous scan).")

elif page == "History":
    h = db.load(); st.dataframe(h, hide_index=True, use_container_width=True)
    st.caption("Status uses last scan price vs stop/T2 (OPEN → TARGET/STOP). Rows tagged MOCK are simulated.")

elif page == "Analytics":
    h = db.load()
    if h.empty: st.info("No stored signals yet.")
    else:
        h["hour"] = pd.to_datetime(h.ts).dt.hour; done = h[h.status.isin(["TARGET", "STOP"])]
        m = st.columns(5); m[0].metric("Signals", len(h)); m[1].metric("Explosive", int((h.tier == "EXPLOSIVE").sum()))
        m[2].metric("Avg score", f"{h.score.mean():.0f}"); m[3].metric("Avg RVOL", f"{h.rvol.mean():.2f}")
        m[4].metric("Target hit", f"{100 * (done.status == 'TARGET').mean():.0f}%" if len(done) else "n/a")
        st.caption(f"Methodology: stored scanner signals, status judged on polled prices (not tick-accurate). Sample size: {len(h)} signals, {len(done)} resolved. "
                   f"Sources: {', '.join(h.source.unique())}.")
        a, c = st.columns(2); a.bar_chart(h.groupby("hour").size()); c.bar_chart(h.score.value_counts().sort_index())

elif page == "Backtest":
    with st.form("bt"):
        a, c, d = st.columns(3)
        syms = a.multiselect("Symbols", SYMBOLS, SYMBOLS[:6]); n = a.slider("Sessions", 5, 20, 15)
        orb = c.selectbox("ORB min", [5, 15, 30]); rv = c.slider("Min RVOL", 0.5, 3.0, 1.5); rr = c.slider("Target (R)", 1.0, 4.0, 2.0)
        sl = d.number_input("Slippage (bps/side)", 0.0, 50.0, 5.0); br = d.number_input("Brokerage (₹/order)", 0.0, 100.0, 20.0)
        go_ = st.form_submit_button("Run")
    if go_:
        try:
            sess = {s: broker.get_sessions(s, n) for s in syms}
            t, ns = backtest.run_backtest(sess, orb, rv, rr, sl, br)
            m = backtest.metrics(t)
            if not m["trades"]: st.info("No trades matched.")
            else:
                k = st.columns(4); k[0].metric("Net P&L", f"₹{m['net_pnl']:,.0f}"); k[1].metric("Win rate", f"{m['win_rate']:.0f}%")
                k[2].metric("Profit factor", f"{m['profit_factor']:.2f}"); k[3].metric("Max drawdown", f"₹{m['max_drawdown']:,.0f}")
                st.write(f"Trades {m['trades']} · Avg R {m['avg_r']:.2f} · Expectancy ₹{m['expectancy']:,.0f}/trade")
                st.line_chart(t.pnl.cumsum().reset_index(drop=True)); st.dataframe(t)
            st.caption(f"Methodology: ORB close-outside + RVOL + VWAP filter, fill at next bar open, stop-first on same-bar hits, EOD exit, "
                       f"1% risk sizing on ₹1L. Sample: {len(t)} trades / {ns} symbols / {n} sessions. "
                       + ("SIMULATED data — results are meaningless for real trading." if broker.is_mock else "Historical results do not predict future results."))
        except BrokerError as e: st.error(str(e))

elif page == "Risk Calculator":
    a, c = st.columns(2)
    cap = a.number_input("Capital (₹)", 1000.0, 1e9, 100000.0); rp = a.number_input("Risk %", 0.1, 10.0, 1.0)
    en = c.number_input("Entry", 0.01, 1e6, 100.0); sp = c.number_input("Stop", 0.01, 1e6, 98.0); lot = c.number_input("Lot size", 1, 100000, 1)
    p = E.position_size(cap, rp, en, sp, int(lot)); d = 1 if en > sp else -1
    lv = E.risk_levels(en, d, None, None, abs(en - sp) / 1.5)
    st.write(f"Max risk **₹{p['max_risk']:,.0f}** · Quantity **{p['quantity']}** · Lots **{p['lots']}** · Capital used ₹{p['capital_used']:,.0f}")
    st.write(f"T1 {lv['t1']:.2f} · T2 {lv['t2']:.2f} · T3 {lv['t3']:.2f} (indicative, R:R to T2 = 2.0)")

if auto: time.sleep(30); st.rerun()
