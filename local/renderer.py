"""Report renderer — renders TEMPER eval and diff reports to the terminal with rich."""

from rich.console import Console
from rich.table import Table
from rich import box
from rich.text import Text
from rich.panel import Panel
from rich.rule import Rule

console = Console()

_DIM_ORDER = [
    "instruction_adherence",
    "tool_accuracy",
    "output_format",
    "skill_trigger",
    "latency_delta",
    "error_recovery",
]

_STATUS_STYLE = {
    "PASSING": "bold green",
    "NEEDS_PATCH": "bold red",
    "RESOLVED": "bold green",
    "STRUCTURAL_LIMITATION": "bold yellow",
}


def _delta_style(delta: float) -> str:
    if delta > 5:
        return "green"
    if delta < -5:
        return "red"
    return "dim white"


def _infer_status(d: dict) -> str:
    """Compute status from fixable/delta when server omits the field."""
    s = d.get("status")
    if s:
        return s
    if not d.get("fixable", True):
        return "STRUCTURAL_LIMITATION"
    delta = d.get("delta", 0)
    return "PASSING" if delta >= -5 else "NEEDS_PATCH"


def _status_text(status: str) -> Text:
    style = _STATUS_STYLE.get(status, "white")
    return Text(status, style=style)


def render_full(report: dict, session_id: str, n_patches: int) -> None:
    """Render the full eval report after @eval."""
    console.print()
    console.print(Panel(
        f"[bold]TEMPER — Eval Report[/bold]\nSession: [cyan]{session_id}[/cyan]",
        border_style="cyan",
        expand=False,
    ))

    dims = report["dimensions"]

    table = Table(box=box.SIMPLE_HEAD, show_footer=False, pad_edge=False)
    table.add_column("Dimension", style="white", min_width=22)
    table.add_column("Baseline", justify="right", style="white")
    table.add_column("Harness", justify="right", style="white")
    table.add_column("Δ", justify="right")
    table.add_column("Status")

    for dim in _DIM_ORDER:
        d = dims.get(dim)
        if d is None:
            continue
        delta = d["delta"]
        delta_str = f"{delta:+.0f}" if delta != 0 else "  0"
        status = _infer_status(d)
        table.add_row(
            dim,
            str(d["baseline_score"]),
            str(d["harness_score"]),
            Text(delta_str, style=_delta_style(delta)),
            _status_text(status),
        )

    console.print(table)

    # Root causes
    needs_root = [(dim, dims[dim]) for dim in _DIM_ORDER
                  if dim in dims and dims[dim].get("root_cause")]
    if needs_root:
        console.print(Rule("Root causes", style="dim"))
        for dim, d in needs_root:
            console.print(f"  [bold]{dim}[/bold]: {d['root_cause']}")
        console.print()

    # Structural limitations
    structural = [(dim, dims[dim]) for dim in _DIM_ORDER
                  if dim in dims and _infer_status(dims[dim]) == "STRUCTURAL_LIMITATION"]
    if structural:
        console.print(Rule("Structural limitations", style="dim yellow"))
        for dim, d in structural:
            reason = d.get("structural_reason") or "(no detail)"
            console.print(f"  [yellow bold]{dim}[/yellow bold]: {reason}")
        console.print()

    if n_patches > 0:
        console.print(f"[green]Patches written to local/patches/ ({n_patches} file{'s' if n_patches != 1 else ''})[/green]")
        console.print("[dim]Run [bold]@patch[/bold] to apply fixes and re-evaluate.[/dim]")
    else:
        console.print("[dim]No patches generated.[/dim]")
    console.print()


def render_diff(orig_report: dict, reeval_report: dict, reeval_session_id: str) -> None:
    """Render the before/after diff report after @patch."""
    console.print()
    console.print(Panel(
        f"[bold]TEMPER — Re-eval Report[/bold]\nSession: [cyan]{reeval_session_id}[/cyan]",
        border_style="green",
        expand=False,
    ))

    orig_dims = orig_report["dimensions"]
    new_dims = reeval_report["dimensions"]
    reevaled = set(new_dims.keys())

    # Patched dimensions table
    table = Table(box=box.SIMPLE_HEAD, show_footer=False, pad_edge=False)
    table.add_column("Dimension", style="white", min_width=22)
    table.add_column("Before", justify="right")
    table.add_column("After", justify="right")
    table.add_column("Move", justify="right")
    table.add_column("Status")

    for dim in _DIM_ORDER:
        if dim not in reevaled:
            continue
        before = orig_dims[dim]["harness_score"]
        after = new_dims[dim]["harness_score"]
        move = after - before
        move_str = f"{move:+.0f}"
        status = _infer_status(new_dims[dim])
        table.add_row(
            dim,
            str(before),
            str(after),
            Text(move_str, style=_delta_style(move)),
            _status_text(status),
        )

    console.print(table)

    # Unchanged dimensions
    unchanged = [dim for dim in _DIM_ORDER if dim in orig_dims and dim not in reevaled]
    if unchanged:
        console.print(Rule("Unchanged dimensions (not re-evaluated)", style="dim"))
        for dim in unchanged:
            d = orig_dims[dim]
            status = _infer_status(d)
            style = _STATUS_STYLE.get(status, "white")
            console.print(
                f"  {dim}: [white]{d['harness_score']}[/white]  [{style}]({status})[/{style}]"
            )

    console.print()
