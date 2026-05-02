from __future__ import annotations

from html import escape
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from arbvoy.backtest.models import BacktestTrade, HistoricalPoint


@dataclass(slots=True)
class BacktestReport:
    points: list[HistoricalPoint]
    trades: list[BacktestTrade]

    @staticmethod
    def _ts(value: object) -> pd.Timestamp:
        ts = pd.Timestamp(value)
        if ts.tzinfo is None:
            return ts.tz_localize("UTC")
        return ts.tz_convert("UTC")

    def write(self, output_dir: str = "artifacts") -> Path | None:
        if not self.points:
            return None
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        trades = sorted(self.trades, key=lambda trade: trade.entry_time)
        df = pd.DataFrame(
            [
                {
                    "timestamp": point.timestamp.isoformat(),
                    "spot": point.btc_spot_mid,
                    "strike": point.contract.strike_usd,
                    "yes_bid": point.contract.yes_bid,
                    "yes_ask": point.contract.yes_ask,
                    "no_bid": point.contract.no_bid,
                    "no_ask": point.contract.no_ask,
                    "implied_prob": point.contract.implied_probability,
                    "model_prob": point.model_prob,
                    "edge_bps": point.edge_bps,
                    "hours_to_expiry": point.hours_to_expiry,
                    "vol": point.vol,
                }
                for point in self.points
            ]
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.sort_values("timestamp").reset_index(drop=True)
        valid = df.dropna(subset=["model_prob", "implied_prob", "edge_bps", "vol"], how="all")
        if not valid.empty:
            window_start = valid["timestamp"].min()
        else:
            window_start = df["timestamp"].min()
        expiry_ts = max(self.points, key=lambda point: point.contract.expiry_dt).contract.expiry_dt
        expiry_ts = pd.Timestamp(expiry_ts)
        if expiry_ts.tzinfo is None:
            expiry_ts = expiry_ts.tz_localize("UTC")
        else:
            expiry_ts = expiry_ts.tz_convert("UTC")
        cutoff = expiry_ts - pd.Timedelta(days=5)
        window_start = max(window_start, cutoff)
        window_end = expiry_ts
        windowed = df[(df["timestamp"] >= window_start) & (df["timestamp"] <= window_end)].copy()
        if windowed.empty:
            windowed = df.copy()
            window_start = df["timestamp"].min()
            window_end = df["timestamp"].max()
        trades_df = pd.DataFrame(
            [
                {
                    "trade_id": trade.trade_id,
                    "entry_time": trade.entry_time.isoformat(),
                    "exit_time": trade.exit_time.isoformat() if trade.exit_time else None,
                    "direction": trade.direction,
                    "net_pnl": trade.net_pnl,
                    "exit_reason": trade.exit_reason,
                }
                for trade in self.trades
            ]
        )
        csv_path = out / "backtest_points.csv"
        trades_csv = out / "backtest_trades.csv"
        html_path = out / "backtest_report.html"
        windowed.to_csv(csv_path, index=False)
        trades_df.to_csv(trades_csv, index=False)

        fig = make_subplots(
            rows=5,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.07,
            specs=[
                [{"secondary_y": True}],
                [{"secondary_y": True}],
                [{"secondary_y": False}],
                [{"secondary_y": True}],
                [{"secondary_y": False}],
            ],
            subplot_titles=(
                "Spot vs Kalshi Ask/Bid",
                "Countdown to Expiry",
                "Model vs Implied Probability",
                "Edge and Volatility Proxy",
                "Cumulative Backtest PnL",
            ),
        )
        fig.add_trace(go.Scatter(x=windowed["timestamp"], y=windowed["spot"], name="BTC Spot", mode="lines"), row=1, col=1, secondary_y=False)
        fig.add_trace(go.Scatter(x=windowed["timestamp"], y=windowed["yes_ask"], name="YES Ask", mode="lines"), row=1, col=1, secondary_y=True)
        fig.add_trace(go.Scatter(x=windowed["timestamp"], y=windowed["yes_bid"], name="YES Bid", mode="lines"), row=1, col=1, secondary_y=True)
        entry_points = []
        exit_points = []
        for trade in trades:
            entry_ts = self._ts(trade.entry_time)
            entry_row = windowed.loc[windowed["timestamp"] == entry_ts]
            if entry_row.empty:
                entry_row = windowed.iloc[[windowed["timestamp"].sub(entry_ts).abs().idxmin()]]
            if not entry_row.empty:
                entry_points.append(
                    {
                        "timestamp": entry_row.iloc[0]["timestamp"],
                        "spot": entry_row.iloc[0]["spot"],
                        "label": trade.direction,
                    }
            )
            if trade.exit_time is not None:
                exit_ts = self._ts(trade.exit_time)
                exit_row = windowed.loc[windowed["timestamp"] == exit_ts]
                if exit_row.empty:
                    exit_row = windowed.iloc[[windowed["timestamp"].sub(exit_ts).abs().idxmin()]]
                if not exit_row.empty:
                    exit_points.append(
                        {
                            "timestamp": exit_row.iloc[0]["timestamp"],
                            "spot": exit_row.iloc[0]["spot"],
                            "label": trade.exit_reason or "exit",
                        }
                    )
            fig.add_vline(x=entry_ts.to_pydatetime(), line_width=1, line_dash="dot", line_color="green", row=1, col=1)
            if trade.exit_time is not None:
                fig.add_vline(x=exit_ts.to_pydatetime(), line_width=1, line_dash="dot", line_color="red", row=1, col=1)
        if entry_points:
            entry_df = pd.DataFrame(entry_points)
            fig.add_trace(
                go.Scatter(
                    x=entry_df["timestamp"],
                    y=entry_df["spot"],
                    mode="markers",
                    name="Entry",
                    marker=dict(size=11, symbol="triangle-up", color="#1b8f3a", line=dict(width=1, color="white")),
                ),
                row=1,
                col=1,
                secondary_y=False,
            )
        if exit_points:
            exit_df = pd.DataFrame(exit_points)
            fig.add_trace(
                go.Scatter(
                    x=exit_df["timestamp"],
                    y=exit_df["spot"],
                    mode="markers",
                    name="Exit",
                    marker=dict(size=11, symbol="triangle-down", color="#b42318", line=dict(width=1, color="white")),
                ),
                row=1,
                col=1,
                secondary_y=False,
            )
        countdown = windowed.dropna(subset=["hours_to_expiry"]).copy()
        if not countdown.empty:
            fig.add_trace(go.Scatter(x=countdown["hours_to_expiry"], y=countdown["spot"], name="Spot vs Expiry", mode="lines"), row=2, col=1, secondary_y=False)
            fig.add_trace(go.Scatter(x=countdown["hours_to_expiry"], y=countdown["yes_ask"], name="YES Ask vs Expiry", mode="lines"), row=2, col=1, secondary_y=True)
            fig.add_trace(go.Scatter(x=countdown["hours_to_expiry"], y=countdown["yes_bid"], name="YES Bid vs Expiry", mode="lines"), row=2, col=1, secondary_y=True)
            fig.update_xaxes(title_text="Hours to Expiry", row=2, col=1)
            fig.update_xaxes(autorange="reversed", row=2, col=1)
        fig.add_trace(go.Scatter(x=windowed["timestamp"], y=windowed["model_prob"], name="Model Prob", mode="lines"), row=3, col=1)
        fig.add_trace(go.Scatter(x=windowed["timestamp"], y=windowed["implied_prob"], name="Implied Prob", mode="lines"), row=3, col=1)
        fig.add_trace(go.Bar(x=windowed["timestamp"], y=windowed["edge_bps"], name="Edge bps"), row=4, col=1, secondary_y=False)
        fig.add_trace(go.Scatter(x=windowed["timestamp"], y=windowed["vol"], name="Volatility", mode="lines"), row=4, col=1, secondary_y=True)
        pnl_curve = []
        total = 0.0
        for trade in self.trades:
            total += trade.net_pnl or 0.0
            pnl_curve.append((trade.exit_time or trade.entry_time, total))
        if pnl_curve:
            pnl_df = pd.DataFrame({"timestamp": [ts.isoformat() for ts, _ in pnl_curve], "cum_pnl": [v for _, v in pnl_curve]})
            fig.add_trace(go.Scatter(x=pnl_df["timestamp"], y=pnl_df["cum_pnl"], name="Cum PnL", mode="lines+markers"), row=5, col=1)
        fig.update_xaxes(range=[window_start, window_end], row=1, col=1)
        fig.update_xaxes(range=[window_start, window_end], row=3, col=1)
        fig.update_xaxes(range=[window_start, window_end], row=4, col=1)
        fig.update_xaxes(range=[window_start, window_end], row=5, col=1)
        fig.update_yaxes(title_text="BTC Spot", row=1, col=1, secondary_y=False)
        fig.update_yaxes(title_text="Kalshi Prob", range=[0, 1], row=1, col=1, secondary_y=True)
        fig.update_yaxes(title_text="BTC Spot", row=2, col=1, secondary_y=False)
        fig.update_yaxes(title_text="Kalshi Prob", range=[0, 1], row=2, col=1, secondary_y=True)
        fig.update_yaxes(title_text="Probability", range=[0, 1], row=3, col=1)
        fig.update_yaxes(title_text="Edge bps", row=4, col=1, secondary_y=False)
        fig.update_yaxes(title_text="Annualized Vol", row=4, col=1, secondary_y=True)
        fig.update_layout(template="plotly_white", title="ArbitrageVoy Backtest Report", height=1350)

        contract = self.points[0].contract
        traded_pnl = sum((trade.net_pnl or 0.0) for trade in trades)
        avg_model_prob = float(windowed["model_prob"].dropna().mean()) if windowed["model_prob"].notna().any() else None
        avg_implied_prob = float(windowed["implied_prob"].dropna().mean()) if windowed["implied_prob"].notna().any() else None
        avg_edge = float(windowed["edge_bps"].dropna().mean()) if windowed["edge_bps"].notna().any() else None
        avg_vol = float(windowed["vol"].dropna().mean()) if windowed["vol"].notna().any() else None
        ask_series = windowed["yes_ask"].dropna()
        bid_series = windowed["yes_bid"].dropna()
        last_row = windowed.iloc[-1]
        summary_rows = [
            ("Ticker", contract.ticker),
            ("Strike", f"{contract.strike_usd:,.2f}"),
            ("Expiry", contract.expiry_dt.isoformat()),
            ("Window", f"{window_start.isoformat()} to {window_end.isoformat()}"),
            ("YES ask at start", f"{float(windowed.iloc[0]['yes_ask']):.4f}"),
            ("YES ask median", f"{float(ask_series.median()):.4f}" if not ask_series.empty else "n/a"),
            ("YES ask range", f"{float(ask_series.min()):.4f} to {float(ask_series.max()):.4f}" if not ask_series.empty else "n/a"),
            ("Points", str(len(windowed))),
            ("Trades", str(len(trades))),
            ("Total PnL", f"{traded_pnl:.4f}"),
            ("Avg model prob", f"{avg_model_prob:.4f}" if avg_model_prob is not None else "n/a"),
            ("Avg implied prob", f"{avg_implied_prob:.4f}" if avg_implied_prob is not None else "n/a"),
            ("Avg edge bps", f"{avg_edge:.2f}" if avg_edge is not None else "n/a"),
            ("Avg vol", f"{avg_vol:.4f}" if avg_vol is not None else "n/a"),
            ("Last spot", f"{float(last_row['spot']):,.2f}"),
            ("Last YES bid/ask", f"{float(last_row['yes_bid']):.2f} / {float(last_row['yes_ask']):.2f}"),
            ("YES bid range", f"{float(bid_series.min()):.4f} to {float(bid_series.max()):.4f}" if not bid_series.empty else "n/a"),
            ("Last implied prob", f"{float(last_row['implied_prob']):.4f}" if pd.notna(last_row["implied_prob"]) else "n/a"),
        ]
        summary_html = "\n".join(
            [
                "<div class='summary-panel'>",
                "<div class='summary-title'>Backtest Summary</div>",
                "<div class='summary-grid'>",
                *[f"<div class='summary-key'>{escape(key)}</div><div class='summary-value'>{escape(value)}</div>" for key, value in summary_rows],
                "</div>",
                "</div>",
            ]
        )
        html = "\n".join(
            [
                "<!doctype html>",
                "<html lang='en'>",
                "<head>",
                "<meta charset='utf-8'/>",
                "<meta name='viewport' content='width=device-width, initial-scale=1'/>",
                "<title>ArbitrageVoy Backtest Report</title>",
                "<style>",
                "body{margin:0;font-family:Segoe UI,Arial,sans-serif;background:#0b1220;color:#e5eefb;}",
                ".wrap{max-width:1400px;margin:0 auto;padding:24px;}",
                ".summary-panel{background:linear-gradient(135deg,#101a33,#0f1b2e);border:1px solid #24324d;border-radius:16px;padding:18px 20px;margin-bottom:20px;box-shadow:0 10px 30px rgba(0,0,0,.28);}",
                ".summary-title{font-size:20px;font-weight:700;margin-bottom:12px;}",
                ".summary-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px 18px;}",
                ".summary-key{color:#8ea4c7;font-size:13px;text-transform:uppercase;letter-spacing:.04em;}",
                ".summary-value{color:#f3f7ff;font-weight:600;word-break:break-word;}",
                "@media (max-width:900px){.summary-grid{grid-template-columns:1fr;}}",
                "</style>",
                "</head>",
                "<body>",
                "<div class='wrap'>",
                summary_html,
                fig.to_html(full_html=False, include_plotlyjs="cdn"),
                "</div>",
                "</body>",
                "</html>",
            ]
        )
        html_path.write_text(html, encoding="utf-8")
        return html_path
