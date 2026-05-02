from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


@dataclass(slots=True)
class DryRunPoint:
    timestamp: datetime
    ticker: str
    expiry_dt: datetime
    spot: float
    strike: float
    yes_bid: float
    yes_ask: float
    no_bid: float
    no_ask: float
    model_prob: float
    implied_prob: float
    edge_bps: float
    vol: float
    dte_days: float


class DryRunReporter:
    def __init__(self, output_dir: str = "artifacts") -> None:
        self._output_dir = Path(output_dir)
        self._points: list[DryRunPoint] = []

    def add_point(self, point: DryRunPoint) -> None:
        self._points.append(point)

    def has_data(self) -> bool:
        return bool(self._points)

    def write(self) -> Path | None:
        if not self._points:
            return None
        self._output_dir.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame([self._to_row(point) for point in self._points])
        csv_path = self._output_dir / "dry_run_report.csv"
        html_path = self._output_dir / "dry_run_report.html"
        df.to_csv(csv_path, index=False)
        fig = make_subplots(
            rows=3,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.08,
            subplot_titles=(
                "Kalshi Bid / Ask vs Spot",
                "Model Probability vs Implied Probability",
                "Edge and Volatility",
            ),
            specs=[[{}], [{}], [{}]],
        )
        fig.add_trace(go.Scatter(x=df["timestamp"], y=df["spot"], name="BTC Spot", mode="lines+markers"), row=1, col=1)
        fig.add_trace(go.Scatter(x=df["timestamp"], y=df["yes_bid"], name="YES Bid", mode="lines+markers"), row=1, col=1)
        fig.add_trace(go.Scatter(x=df["timestamp"], y=df["yes_ask"], name="YES Ask", mode="lines+markers"), row=1, col=1)
        fig.add_trace(go.Scatter(x=df["timestamp"], y=df["no_bid"], name="NO Bid", mode="lines+markers"), row=1, col=1)
        fig.add_trace(go.Scatter(x=df["timestamp"], y=df["no_ask"], name="NO Ask", mode="lines+markers"), row=1, col=1)
        fig.add_trace(go.Scatter(x=df["timestamp"], y=df["model_prob"], name="Model Prob", mode="lines+markers"), row=2, col=1)
        fig.add_trace(go.Scatter(x=df["timestamp"], y=df["implied_prob"], name="Implied Prob", mode="lines+markers"), row=2, col=1)
        fig.add_trace(go.Bar(x=df["timestamp"], y=df["edge_bps"], name="Edge bps"), row=3, col=1)
        fig.add_trace(go.Scatter(x=df["timestamp"], y=df["vol"], name="Annualized Vol", mode="lines+markers"), row=3, col=1)
        fig.update_layout(
            title="ArbitrageVoy Dry-Run Market Report",
            xaxis_title="Cycle Time",
            yaxis_title="Price / Probability",
            template="plotly_white",
            height=1100,
            legend_orientation="h",
        )
        fig.write_html(str(html_path), include_plotlyjs="cdn")
        return html_path

    @staticmethod
    def _to_row(point: DryRunPoint) -> dict[str, Any]:
        return {
            "timestamp": point.timestamp.astimezone(timezone.utc).isoformat(),
            "ticker": point.ticker,
            "expiry_dt": point.expiry_dt.astimezone(timezone.utc).isoformat(),
            "spot": point.spot,
            "strike": point.strike,
            "yes_bid": point.yes_bid,
            "yes_ask": point.yes_ask,
            "no_bid": point.no_bid,
            "no_ask": point.no_ask,
            "model_prob": point.model_prob,
            "implied_prob": point.implied_prob,
            "edge_bps": point.edge_bps,
            "vol": point.vol,
            "dte_days": point.dte_days,
        }

