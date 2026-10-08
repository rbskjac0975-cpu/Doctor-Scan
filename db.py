import sqlite3, datetime as dt
from .config import DB_PATH

def _c():
    c = sqlite3.connect(DB_PATH)
    c.execute("""CREATE TABLE IF NOT EXISTS signals(id INTEGER PRIMARY KEY, symbol TEXT, ts TEXT, day TEXT, direction TEXT,
      score INT, tier TEXT, rvol REAL, orb TEXT, vwap TEXT, option TEXT, entry REAL, stop REAL, target REAL, status TEXT, source TEXT,
      UNIQUE(symbol, day, direction, source))""")
    return c

def save(row, risk, source):
    with _c() as c:
        c.execute("INSERT OR IGNORE INTO signals(symbol,ts,day,direction,score,tier,rvol,orb,vwap,option,entry,stop,target,status,source) "
                  "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'OPEN',?)",
                  (row["symbol"], dt.datetime.now().isoformat(timespec="seconds"), dt.date.today().isoformat(), row["direction"],
                   int(row["score"]), row["tier"], row["rvol"], row["orb"], row["vwap_side"], row.get("option", ""),
                   risk["entry"], risk["stop"], risk["t2"], source))

def update_status(prices: dict):
    with _c() as c:
        for r in c.execute("SELECT id,symbol,direction,stop,target FROM signals WHERE status='OPEN' AND day=?", (dt.date.today().isoformat(),)).fetchall():
            p = prices.get(r[1]); long = r[2] == "BULLISH"
            if p is None: continue
            st = "STOP" if (p <= r[3] if long else p >= r[3]) else "TARGET" if (p >= r[4] if long else p <= r[4]) else None
            if st: c.execute("UPDATE signals SET status=? WHERE id=?", (st, r[0]))

def load():
    import pandas as pd
    with _c() as c: return pd.read_sql("SELECT * FROM signals ORDER BY id DESC", c)
