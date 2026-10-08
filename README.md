# 🩺 DOCTOR SCAN — NSE F&O scanner (Streamlit)

Original implementation. Modes: `DATA_PROVIDER=MOCK` (simulated, labelled "MOCK DATA") or `ANGEL_ONE` (live REST via SmartAPI). Live mode never falls back to mock.

## Run
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # edit
streamlit run app.py
python -m pytest -q tests
```

## Angel One setup
1. Create a SmartAPI app at smartapi.angelone.in → API key.
2. Enable TOTP on your Angel One account; copy the **TOTP secret** (base32) shown at setup.
3. Fill `.env`: `DATA_PROVIDER=ANGEL_ONE`, `ANGEL_ONE_API_KEY`, `ANGEL_ONE_CLIENT_CODE`, `ANGEL_ONE_PASSWORD` (PIN), `ANGEL_ONE_TOTP`.
4. Start the app → sidebar → **Login**. The instrument master (OpenAPIScripMaster.json) is downloaded and cached 24h; lot sizes come from it.
Secrets are read from env only, never logged or shown in the UI.

## Layout
`doctorscan/engine.py` (RVOL, VWAP, ORB state machine, candle quality, breadth, sectors, score, conviction, risk, sizing, option ranking) ·
`scanner.py` · `backtest.py` · `alerts.py` (+Telegram) · `db.py` (SQLite) · `brokers/{base,mock,angel_one}.py`.

## Scanner logic (summary)
- **RVOL** = cumulative volume at minute M ÷ mean cumulative volume at minute M over ≤20 prior sessions.
- **VWAP** = Σ(typical price × volume) ÷ Σ volume. **ORB** states: WATCH→TESTING→BREAKOUT→CONFIRMED→RETEST→CONTINUATION / FAILED (confirmation: 2nd close outside + RVOL + VWAP side).
- **Score (100)**: RVOL 25, momentum 15, candle 10, ORB 15, VWAP 10, liquidity 5, breadth 10, sector 5, timing 5. Tiers 90/75/60.
- **Conviction** is a model-confidence index, not a probability of profit.

## Not included / limits (be aware)
- Not built: React/FastAPI/Postgres/Redis/Celery/Docker/Nginx stack, JWT auth/roles/admin, subscriptions, 5m candle tables.
- Live feed is **REST polling**, not SmartWebSocketV2 (needs a separate worker process). Many symbols × REST calls will hit SmartAPI rate limits; start with a small universe.
- Live option chain is not implemented (mock only). Exchange holidays are not modelled. Sector map is a static list.
- Live adapter is unit-tested only against mocked SmartConnect; it has **not** been run with real credentials.

## Compliance
Broker/exchange data is licensed to you personally: follow Angel One's API terms and NSE data-redistribution rules, do not share credentials or resell data, and check SEBI rules before offering signals commercially.
> Market signals are informational and are not financial advice. Trading involves risk. Verify all signals independently.
