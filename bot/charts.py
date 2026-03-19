"""Generate equity curve charts for admin stats."""

import io
from typing import Optional

STARTING_BALANCE = 50_000.0

ASSET_COLORS = {
    "XAUUSD": "#FFD700",
    "BTC":    "#F7931A",
    "EURUSD": "#4A90E2",
    "SPX":    "#2ECC71",
    "BRENT":  "#8B4513",
}


def _build_equity_series(trades: list[dict], starting: float = STARTING_BALANCE) -> tuple[list, list]:
    """Return (labels, equity_values) from a sorted list of trade dicts with 'pnl' and 'created_at'."""
    equity = starting
    equities = [equity]
    labels = ["Start"]
    for t in trades:
        equity += t["pnl"]
        equities.append(round(equity, 2))
        ts = t.get("created_at", "")
        label = str(ts)[:10] if ts else "?"
        labels.append(label)
    return labels, equities


def generate_equity_chart(equity_trades: list[dict]) -> Optional[bytes]:
    """Generate overall equity curve PNG. Returns bytes or None if no data."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.ticker as mticker
    except ImportError:
        return None

    if not equity_trades:
        return None

    labels, equities = _build_equity_series(equity_trades)
    total_pnl = equities[-1] - STARTING_BALANCE
    color = "#2ECC71" if total_pnl >= 0 else "#E74C3C"

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(range(len(equities)), equities, color=color, linewidth=2, marker="o", markersize=4)
    ax.axhline(y=STARTING_BALANCE, color="#AAAAAA", linestyle="--", linewidth=1, alpha=0.7)
    ax.fill_between(range(len(equities)), STARTING_BALANCE, equities,
                    where=[e >= STARTING_BALANCE for e in equities],
                    alpha=0.15, color="#2ECC71")
    ax.fill_between(range(len(equities)), STARTING_BALANCE, equities,
                    where=[e < STARTING_BALANCE for e in equities],
                    alpha=0.15, color="#E74C3C")

    pnl_sign = "+" if total_pnl >= 0 else ""
    ax.set_title(
        f"Overall Equity Curve  |  Start: ${STARTING_BALANCE:,.0f}  "
        f"Current: ${equities[-1]:,.2f}  P&L: {pnl_sign}${total_pnl:,.2f}",
        fontsize=11, pad=10,
    )
    ax.set_ylabel("Balance ($)")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x:,.0f}"))
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=7)
    ax.grid(axis="y", alpha=0.3)
    ax.set_facecolor("#1A1A2E")
    fig.patch.set_facecolor("#1A1A2E")
    ax.tick_params(colors="white")
    ax.yaxis.label.set_color("white")
    ax.title.set_color("white")
    for spine in ax.spines.values():
        spine.set_edgecolor("#444444")

    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def generate_per_asset_chart(by_asset: dict, equity_trades: list[dict]) -> Optional[bytes]:
    """Generate a subplot grid showing equity curve per asset."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.ticker as mticker
    except ImportError:
        return None

    assets_with_trades = [
        asset for asset, data in by_asset.items()
        if data.get("trades")
    ]
    if not assets_with_trades:
        return None

    n = len(assets_with_trades)
    cols = min(n, 3)
    rows = (n + cols - 1) // cols

    fig, axes = plt.subplots(rows, cols, figsize=(cols * 5, rows * 3.5))
    fig.patch.set_facecolor("#1A1A2E")

    # Flatten axes array
    if n == 1:
        axes = [axes]
    elif rows == 1:
        axes = list(axes)
    else:
        axes = [ax for row in axes for ax in row]

    for idx, asset in enumerate(assets_with_trades):
        ax = axes[idx]
        trades = sorted(by_asset[asset].get("trades", []), key=lambda t: t.get("created_at") or "")
        labels, equities = _build_equity_series(trades)
        total_pnl = equities[-1] - STARTING_BALANCE
        color = ASSET_COLORS.get(asset, "#4A90E2")
        line_color = "#2ECC71" if total_pnl >= 0 else "#E74C3C"

        ax.plot(range(len(equities)), equities, color=line_color, linewidth=1.5, marker="o", markersize=3)
        ax.axhline(y=STARTING_BALANCE, color="#AAAAAA", linestyle="--", linewidth=0.8, alpha=0.6)
        ax.fill_between(range(len(equities)), STARTING_BALANCE, equities,
                        where=[e >= STARTING_BALANCE for e in equities],
                        alpha=0.2, color="#2ECC71")
        ax.fill_between(range(len(equities)), STARTING_BALANCE, equities,
                        where=[e < STARTING_BALANCE for e in equities],
                        alpha=0.2, color="#E74C3C")

        pnl_sign = "+" if total_pnl >= 0 else ""
        ax.set_title(f"{asset}  P&L: {pnl_sign}${total_pnl:,.2f}", fontsize=9, color="white")
        ax.set_facecolor("#1A1A2E")
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x:,.0f}"))
        ax.tick_params(colors="white", labelsize=7)
        ax.yaxis.label.set_color("white")
        ax.grid(axis="y", alpha=0.3)
        for spine in ax.spines.values():
            spine.set_edgecolor("#333333")
        ax.set_xticks([])

    # Hide unused subplots
    for idx in range(n, len(axes)):
        axes[idx].set_visible(False)

    fig.suptitle("Per-Asset Equity Curves", color="white", fontsize=12, y=1.01)
    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read()
