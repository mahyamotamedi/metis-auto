"""Figures for the full-dataset EDA, drawn from feature-only tables and the claims
ledger. English labels, no content, no IDs.

    python scripts/full_eda_figures.py
"""

from __future__ import annotations

import glob
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

T = Path("reports/full_eda/tables")
F = Path("reports/full_eda/figures")
F.mkdir(parents=True, exist_ok=True)
BLUE, ORANGE, GREY, GREEN = "#2a6f97", "#e07a1f", "#8a8f98", "#3a8f5c"
plt.rcParams.update(
    {
        "font.size": 10,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.dpi": 130,
    }
)


def save(fig, name):
    fig.tight_layout()
    fig.savefig(F / f"{name}.png")
    plt.close(fig)


def fig_language():
    d = pd.read_csv(T / "language_user_requests.csv").sort_values(
        "request_share", ascending=True
    )
    fig, ax = plt.subplots(figsize=(7, 3.6))
    y = range(len(d))
    ax.barh(
        [i + 0.2 for i in y],
        d["request_share"] * 100,
        height=0.4,
        color=BLUE,
        label="share of requests",
    )
    ax.barh(
        [i - 0.2 for i in y],
        d["billed_input_token_share"] * 100,
        height=0.4,
        color=ORANGE,
        label="share of billed input tokens",
    )
    ax.set_yticks(list(y), d["lang"])
    ax.set_xlabel("percent (heuristic language label of the USER message)")
    ax.legend(frameon=False, loc="lower right")
    ax.set_title("Language mix: requests vs billed input tokens")
    save(fig, "fig1_language_mix")


def fig_cost():
    led = pd.concat(
        [pd.read_csv(T / f"claims_ledger_{x}.csv") for x in "abc"]
    ).set_index("claim_id")["value"]
    mu = pd.read_csv(T / "model_usage.csv").sort_values("cost", ascending=False).head(8)
    fig, axs = plt.subplots(
        1, 2, figsize=(9.5, 3.6), gridspec_kw={"width_ratios": [1, 1.6]}
    )
    parts = {
        k: led[f"cost.split.{k}"] * 100
        for k in ("input", "output", "cached_input", "per_call")
    }
    axs[0].bar(
        ["input\ntokens", "output\ntokens", "cached\ninput", "per-call\nfees"],
        list(parts.values()),
        color=[BLUE, BLUE, BLUE, ORANGE],
    )
    axs[0].set_ylabel("% of recorded cost")
    axs[0].set_title("What the recorded cost is made of")
    lab = mu["model"].str.replace("-", "-​")
    x = range(len(mu))
    axs[1].bar(
        [i - 0.2 for i in x],
        mu["request_share"] * 100,
        0.4,
        color=BLUE,
        label="requests",
    )
    axs[1].bar(
        [i + 0.2 for i in x],
        mu["cost_share"] * 100,
        0.4,
        color=ORANGE,
        label="recorded cost",
    )
    axs[1].set_xticks(list(x), lab, rotation=40, ha="right", fontsize=8)
    axs[1].set_ylabel("percent")
    axs[1].legend(frameon=False)
    axs[1].set_title("Configured model label: requests vs cost")
    save(fig, "fig2_cost_composition")


def fig_history():
    d = pd.read_csv(T / "history_growth.csv")
    order = ["0", "1", "2", "3-4", "5-9", "10-19", "20+"]
    d["turn_bucket"] = d["tb"].astype(str)
    d = d.set_index("turn_bucket").loc[order]
    fig, ax = plt.subplots(figsize=(7, 3.6))
    ax.plot(
        order,
        d["median_input_tokens"],
        marker="o",
        color=BLUE,
        label="median billed input tokens",
    )
    ax.set_ylabel("tokens")
    ax.set_ylim(bottom=0)
    ax2 = ax.twinx()
    ax2.plot(
        order,
        d["median_logged_prior_chars"],
        marker="s",
        color=ORANGE,
        label="median logged prior characters",
    )
    ax2.set_ylim(bottom=0)
    ax2.set_ylabel("characters logged before the request")
    ax2.spines["right"].set_visible(True)
    ax.set_xlabel("turn in session")
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, frameon=False, loc="upper left")
    ax.set_title("Billed input stays modest while logged history keeps growing")
    save(fig, "fig3_history_growth")


def fig_cache():
    d = pd.read_csv(T / "exact_cache_variants.csv")
    d = d[d["scope"].isin(["global", "session"])]
    labs = ["text_only", "bot+text", "bot+full_history", "bot+full_history+rag_set"]
    fig, axs = plt.subplots(1, 2, figsize=(9.5, 3.6), sharey=True)
    for ax, col, ttl in (
        (axs[0], "hit_rate_eligible", "candidate hit rate (eligible requests)"),
        (
            axs[1],
            "avoided_cost_share",
            "recorded cost of candidate hits / total recorded cost",
        ),
    ):
        for sc, color, off in (("global", BLUE, -0.2), ("session", ORANGE, 0.2)):
            v = d[d["scope"] == sc].set_index("variant").loc[labs, col] * 100
            ax.barh(
                [i + off for i in range(4)], v, 0.4, color=color, label=f"scope: {sc}"
            )
        ax.set_title(ttl, fontsize=9)
        ax.set_xlabel("percent")
    axs[0].set_yticks(
        range(4),
        [
            "request text only",
            "bot + text",
            "bot + full history",
            "bot + history + RAG set",
        ],
    )
    axs[0].invert_yaxis()
    axs[0].legend(frameon=False)
    fig.suptitle("Exact cache replay: candidate hits, not validated hits", fontsize=10)
    save(fig, "fig4_exact_cache")


def fig_rag():
    ch = pd.concat(
        [
            pd.read_parquet(f, columns=["n_chars"])
            for f in sorted(glob.glob("data/derived/full_eda/chunks/*.parquet"))
        ]
    )
    fig, ax = plt.subplots(figsize=(7, 3.4))
    ax.hist(ch["n_chars"].clip(upper=3000), bins=120, color=BLUE)
    ax.set_xlabel("characters per retrieved chunk (clipped at 3,000)")
    ax.set_ylabel("chunk rows")
    ax.set_title("Chunk lengths pile up near a ceiling of roughly 2,500 characters")
    save(fig, "fig5_rag_chunk_lengths")


def fig_instructions():
    d = pd.read_csv(T / "instruction_groups_top.csv").head(15)
    fig, ax = plt.subplots(figsize=(7, 3.6))
    ax.bar(
        d["rank"].astype(str),
        d["request_share"].cumsum() * 100,
        color=GREY,
        label="cumulative",
    )
    ax.bar(
        d["rank"].astype(str), d["request_share"] * 100, color=BLUE, label="per group"
    )
    ax.set_xlabel("instruction group, ranked by requests")
    ax.set_ylabel("% of requests with instruction text")
    ax.legend(frameon=False)
    ax.set_title("A few instruction texts cover most requests")
    save(fig, "fig6_instruction_groups")


if __name__ == "__main__":
    for fn in (
        fig_language,
        fig_cost,
        fig_history,
        fig_cache,
        fig_rag,
        fig_instructions,
    ):
        fn()
    print(sorted(p.name for p in F.glob("*.png")))
