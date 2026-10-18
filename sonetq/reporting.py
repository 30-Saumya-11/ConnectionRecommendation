"""Turns numbers into tables (markdown) and pictures (png)."""
import os


def md_table(rows, cols, fmt=None):
    fmt = fmt or {}
    head = "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n"
    body = ""
    for r in rows:
        cells = []
        for c in cols:
            v = r[c]
            cells.append(fmt.get(c, "{}").format(v) if not isinstance(v, str) else v)
        body += "| " + " | ".join(cells) + " |\n"
    return head + body


def make_plots(outdir, final_rows, sweep_rows, val_rows, index_rows):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return []
    made = []

    # 1. quality of the four approaches
    fig, ax = plt.subplots(figsize=(7, 4))
    names = [r["model"] for r in final_rows]
    x = range(len(names))
    for j, m in enumerate(("roc_auc", "avg_precision", "hits_at_k")):
        ax.bar([i + 0.27 * (j - 1) for i in x], [r[m] for r in final_rows], width=0.27, label=m)
    ax.set_xticks(list(x)); ax.set_xticklabels([n.split(" (")[0] for n in names], fontsize=7, rotation=15)
    ax.set_title("Prediction quality (mean over snapshots 19-24)"); ax.legend()
    fig.tight_layout(); p = os.path.join(outdir, "plot_quality.png"); fig.savefig(p, dpi=150); plt.close(fig)
    made.append(p)

    # 2. cache hit rate vs cache size
    fig, ax = plt.subplots(figsize=(6, 4))
    for pol in ("LRU", "FIFO"):
        rr = [r for r in sweep_rows if r["policy"] == pol]
        ax.plot([r["cache_size"] for r in rr], [r["hit_rate"] for r in rr], marker="o", label=pol)
    ax.set_xlabel("cache size (snapshots)"); ax.set_ylabel("hit rate"); ax.set_title("Cache hit rate vs size")
    ax.legend(); fig.tight_layout()
    p = os.path.join(outdir, "plot_cache_hit_rate.png"); fig.savefig(p, dpi=150); plt.close(fig); made.append(p)

    # 3. data-access time vs cache size
    fig, ax = plt.subplots(figsize=(6, 4))
    for pol in ("LRU", "FIFO"):
        rr = [r for r in sweep_rows if r["policy"] == pol]
        ax.plot([r["cache_size"] for r in rr], [r["data_access_time_s"] for r in rr], marker="o", label=pol)
    ax.set_xlabel("cache size (snapshots)"); ax.set_ylabel("data-access time (s)")
    ax.set_title("Data-access time vs cache size"); ax.legend(); fig.tight_layout()
    p = os.path.join(outdir, "plot_cache_time.png"); fig.savefig(p, dpi=150); plt.close(fig); made.append(p)

    # 4. validation curve for lambda
    fig, ax = plt.subplots(figsize=(6, 4))
    for w in sorted({r["window"] for r in val_rows}):
        rr = [r for r in val_rows if r["window"] == w]
        ax.plot([r["lambda"] for r in rr], [r["score"] for r in rr], marker="o", label=f"window={w}")
    ax.set_xlabel("lambda (decay)"); ax.set_ylabel("validation score (last 6 history snapshots)")
    ax.set_title("Choosing lambda on validation data"); ax.legend(); fig.tight_layout()
    p = os.path.join(outdir, "plot_lambda_validation.png"); fig.savefig(p, dpi=150); plt.close(fig); made.append(p)
    return made
