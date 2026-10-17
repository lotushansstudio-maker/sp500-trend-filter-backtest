"""
S&P 500 10-month moving-average trend filter, 1950 to today.

Rule: at each month-end, hold the S&P 500 if its price is above its
10-month simple moving average, otherwise hold cash. The signal is only
acted on the following month (no look-ahead), and every switch costs 0.1%.

Author: Hanyu (Lotus) Ke
"""
import argparse, json, os
import numpy as np
import pandas as pd

DATA_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500/main/data/data.csv"
DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "sp500_shiller_monthly.csv")
START = "1950-01-01"
COST = 0.001  # one-way cost per switch


def load(refresh=False):
    if refresh or not os.path.exists(DATA_FILE):
        pd.read_csv(DATA_URL).to_csv(DATA_FILE, index=False)
    d = pd.read_csv(DATA_FILE, parse_dates=["Date"]).set_index("Date")
    d = d["1949-01-01":]
    px = d["SP500"]
    # Shiller dividends are annualised; the latest months are reported as 0 until filled in.
    div = d["Dividend"].replace(0, np.nan).ffill()
    return px, div


def strategy(px, ret, n=10, lag=1, cost=COST):
    """Monthly returns of the trend filter. lag=1 trades next month, lag=2 waits one more month."""
    sig = (px > px.rolling(n).mean()).astype(float)
    pos = sig.shift(lag)
    switches = pos.diff().abs().fillna(0)
    return pos * ret - switches * cost, pos, switches


def stats(r, pos=None, sw=None):
    r = r.dropna()
    eq = (1 + r).cumprod()
    yrs = len(r) / 12
    vol = r.std() * np.sqrt(12)
    o = {
        "cagr": eq.iloc[-1] ** (1 / yrs) - 1,
        "vol": vol,
        "sharpe": r.mean() * 12 / vol,  # cash earns 0, so this is a return/vol ratio
        "maxdd": (eq / eq.cummax() - 1).min(),
    }
    if pos is not None:
        o["time_invested"] = pos.loc[r.index].mean()
        o["switches_per_year"] = sw.loc[r.index].sum() / yrs
    return o


def pct(x):
    return f"{x*100:.1f}%"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="re-download the data")
    ap.add_argument("--no-charts", action="store_true")
    a = ap.parse_args()

    px, div = load(a.refresh)
    price_ret = px.pct_change()
    total_ret = price_ret + (div.shift(1) / 12) / px.shift(1)

    res, rows = {}, []
    variants = {
        "Main: price return, trade next month": (price_ret, 1),
        "Robustness: trade two months later": (price_ret, 2),
        "Robustness: incl. dividends, cash at 0%": (total_ret, 1),
    }
    for name, (ret, lag) in variants.items():
        s, pos, sw = strategy(px, ret, lag=lag)
        st, bh = stats(s[START:], pos, sw), stats(ret[START:])
        res[name] = {"strategy": st, "buy_hold": bh}
        rows.append((name, st, bh))

    # Split at 2007, the year the 10-month rule was published (Faber, 2007).
    s1, pos1, sw1 = strategy(px, price_ret)
    for label, a_, b_ in [("1950-2006", START, "2006-12-31"), ("2007-today (after publication)", "2007-01-01", None)]:
        res[label] = {"strategy": stats(s1[a_:b_], pos1, sw1), "buy_hold": stats(price_ret[a_:b_])}
        rows.append((label, res[label]["strategy"], res[label]["buy_hold"]))

    grid = []
    for n in range(6, 15):
        s, p, w = strategy(px, price_ret, n=n)
        grid.append({"months": n, **stats(s[START:], p, w)})
    res["sma_length_grid"] = grid

    S, B = s1[START:].fillna(0), price_ret[START:].fillna(0)
    ep = lambda a_, b_: {"strategy": (1 + S[a_:b_]).prod() - 1, "buy_hold": (1 + B[a_:b_]).prod() - 1}
    res["episodes"] = {
        "Dot-com 2000-02": ep("2000-09", "2002-09"),
        "GFC 2007-09": ep("2007-11", "2009-02"),
        "COVID 2020": ep("2020-02", "2020-03"),
        "Rate shock 2022": ep("2022-01", "2022-09"),
    }
    sma = px.rolling(10).mean()
    res["latest"] = {"month": str(px.index[-1].date())[:7], "price": float(px.iloc[-1]),
                     "sma10": round(float(sma.iloc[-1]), 2), "invested": bool(px.iloc[-1] > sma.iloc[-1])}

    os.makedirs("results", exist_ok=True)
    json.dump(res, open("results/results.json", "w"), indent=1, default=float)

    print(f"{'':42s} {'CAGR':>7s} {'Sharpe':>7s} {'MaxDD':>7s} | {'B&H CAGR':>8s} {'Sharpe':>7s} {'MaxDD':>7s}")
    for name, st, bh in rows:
        print(f"{name:42s} {pct(st['cagr']):>7s} {st['sharpe']:7.2f} {pct(st['maxdd']):>7s} | "
              f"{pct(bh['cagr']):>8s} {bh['sharpe']:7.2f} {pct(bh['maxdd']):>7s}")
    print("\nSMA length:", ", ".join(f"{g['months']}m {g['sharpe']:.2f}" for g in grid))
    print("Episodes:", {k: (pct(v["strategy"]), pct(v["buy_hold"])) for k, v in res["episodes"].items()})
    print("Latest:", res["latest"])

    if not a.no_charts:
        charts(S, B, s1, price_ret, grid)


def charts(S, B, s1, price_ret, grid):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.grid": True, "axes.axisbelow": True, "grid.color": "#e3e1dc", "grid.linewidth": 0.6})
    C_S, C_B = "#1f5f8b", "#9a9a9a"
    eqS, eqB = (1 + S).cumprod(), (1 + B).cumprod()
    s2, _, _ = strategy(load()[0], price_ret, lag=2)
    eq2 = (1 + s2[START:].fillna(0)).cumprod()

    fig, ax = plt.subplots(figsize=(9, 4.2))
    ax.plot(eqB.index, eqB, color=C_B, lw=1.4, label="Buy and hold")
    ax.plot(eq2.index, eq2, color=C_S, lw=1.2, ls="--", alpha=0.7, label="Trend filter, 2-month delay")
    ax.plot(eqS.index, eqS, color=C_S, lw=1.8, label="Trend filter (10-month SMA)")
    ax.set_yscale("log"); ax.set_ylabel("Growth of $1 (log scale, price only)")
    ax.set_title("S&P 500 with a 10-month trend filter, 1950 to 2026", loc="left", fontsize=11)
    ax.legend(frameon=False, loc="upper left")
    fig.tight_layout(); fig.savefig("charts/equity_curve.png", dpi=160); plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 3.2))
    ddB, ddS = eqB / eqB.cummax() - 1, eqS / eqS.cummax() - 1
    ax.fill_between(ddB.index, ddB * 100, 0, color=C_B, alpha=0.35, lw=0, label="Buy and hold")
    ax.plot(ddS.index, ddS * 100, color=C_S, lw=1.3, label="Trend filter")
    ax.set_ylabel("Drawdown from peak (%)")
    ax.set_title("Drawdowns", loc="left", fontsize=11)
    ax.legend(frameon=False, loc="lower left")
    fig.tight_layout(); fig.savefig("charts/drawdowns.png", dpi=160); plt.close(fig)

    fig, ax = plt.subplots(figsize=(6, 3.2))
    ns = [g["months"] for g in grid]
    ax.bar(ns, [g["sharpe"] for g in grid], color=[C_S if n == 10 else "#a9c3d6" for n in ns], width=0.6)
    ax.axhline(stats(B)["sharpe"], color=C_B, lw=1.2, ls="--")
    ax.text(14.4, stats(B)["sharpe"] + 0.02, "Buy and hold", ha="right", color="#666", fontsize=9)
    ax.set_xticks(ns); ax.set_xlabel("Moving-average length (months)"); ax.set_ylabel("Return / volatility")
    ax.set_title("Result does not hinge on picking 10 months", loc="left", fontsize=11)
    fig.tight_layout(); fig.savefig("charts/sma_length.png", dpi=160); plt.close(fig)


if __name__ == "__main__":
    main()
