"""
Command Line Interface
======================

Typer-based CLI for running scans, viewing leads, and managing the system.

Usage:
    deepscan scan --source news --states CA,TX
    deepscan leads --hot --limit 20
    deepscan export --format csv --min-score 7
    deepscan serve --port 8000
"""

import asyncio
from datetime import datetime
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

app = typer.Typer(
    name="deepscan",
    help="Industry Deep Scan - AI-powered lead generation for MCA brokers",
    add_completion=True,
)

console = Console()


def run_async(coro):
    """Helper to run async functions in sync CLI context."""
    return asyncio.get_event_loop().run_until_complete(coro)


# === Scan Commands ===


@app.command()
def scan(
    source: Optional[str] = typer.Option(
        None,
        "--source", "-s",
        help="Source to scan (news, yelp, bbb, listings, liens, permits) or 'all'",
    ),
    states: Optional[str] = typer.Option(
        None,
        "--states",
        help="Comma-separated state codes (e.g., CA,TX,FL)",
    ),
    industries: Optional[str] = typer.Option(
        None,
        "--industries",
        help="Comma-separated industries (e.g., construction,restaurant)",
    ),
    parallel: bool = typer.Option(
        False,
        "--parallel",
        help="Run sources in parallel (faster but more resource intensive)",
    ),
):
    """
    Run a scan to find new leads.

    Examples:
        deepscan scan --source news --states CA,TX
        deepscan scan --source all --industries construction,trucking
        deepscan scan --parallel
    """
    from industry_deep_scan.engine import DeepScanEngine
    from industry_deep_scan.models import SourceType

    state_list = states.split(",") if states else None
    industry_list = industries.split(",") if industries else None

    async def do_scan():
        async with DeepScanEngine() as engine:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                if source and source != "all":
                    progress.add_task(f"Scanning {source}...", total=None)
                    source_type = SourceType(source)
                    result = await engine.run_source_scan(
                        source_type,
                        states=state_list,
                        industries=industry_list,
                    )
                    return {"sources": {source: result}, "totals": result}
                else:
                    progress.add_task("Running full scan...", total=None)
                    return await engine.run_full_scan(
                        states=state_list,
                        industries=industry_list,
                        parallel=parallel,
                    )

    result = run_async(do_scan())

    # Display results
    console.print()
    console.print(Panel.fit(
        f"[bold green]Scan Complete![/bold green]\n\n"
        f"Signals Found: [cyan]{result['totals'].get('signals_found', 0)}[/cyan]\n"
        f"Errors: [red]{result['totals'].get('errors', 0)}[/red]",
        title="Scan Results",
    ))

    # Show per-source breakdown
    if "sources" in result and len(result["sources"]) > 1:
        table = Table(title="Results by Source")
        table.add_column("Source", style="cyan")
        table.add_column("Signals", justify="right")
        table.add_column("Errors", justify="right", style="red")

        for source_name, source_result in result["sources"].items():
            if isinstance(source_result, dict):
                table.add_row(
                    source_name,
                    str(source_result.get("signals_found", 0)),
                    str(source_result.get("errors", 0)),
                )

        console.print(table)


# === Leads Commands ===


@app.command()
def leads(
    hot: bool = typer.Option(
        False,
        "--hot",
        help="Show only hot leads (critical/high priority)",
    ),
    status: Optional[str] = typer.Option(
        None,
        "--status",
        help="Filter by status (new, contacted, qualified)",
    ),
    state: Optional[str] = typer.Option(
        None,
        "--state",
        help="Filter by state code",
    ),
    industry: Optional[str] = typer.Option(
        None,
        "--industry",
        help="Filter by industry",
    ),
    min_score: float = typer.Option(
        0,
        "--min-score",
        help="Minimum lead score (0-10)",
    ),
    limit: int = typer.Option(
        20,
        "--limit", "-n",
        help="Number of leads to show",
    ),
):
    """
    View leads in the database.

    Examples:
        deepscan leads --hot --limit 10
        deepscan leads --state CA --industry construction
        deepscan leads --min-score 7
    """
    from industry_deep_scan.database import BusinessRepository, get_session
    from industry_deep_scan.engine import DeepScanEngine
    from industry_deep_scan.models import LeadStatus, SignalPriority

    async def get_leads():
        if hot:
            async with DeepScanEngine() as engine:
                return await engine.get_hot_leads(limit)
        else:
            async with get_session() as session:
                repo = BusinessRepository(session)
                lead_status = LeadStatus(status) if status else None
                businesses = await repo.get_leads(
                    status=lead_status,
                    min_score=min_score,
                    state=state,
                    industry=industry,
                    limit=limit,
                )
                return [
                    {
                        "business_name": b.name,
                        "industry": b.industry,
                        "location": f"{b.city}, {b.state}" if b.city else b.state,
                        "phone": b.phone,
                        "score": b.lead_score,
                        "priority": b.priority.value,
                        "status": b.status.value,
                    }
                    for b in businesses
                ]

    result = run_async(get_leads())

    if not result:
        console.print("[yellow]No leads found matching criteria.[/yellow]")
        return

    # Display as table
    table = Table(title=f"Leads ({len(result)} found)")
    table.add_column("Business", style="cyan", no_wrap=True)
    table.add_column("Industry")
    table.add_column("Location")
    table.add_column("Phone")
    table.add_column("Score", justify="right")
    table.add_column("Priority")
    table.add_column("Status")

    priority_colors = {
        "critical": "bold red",
        "high": "red",
        "medium": "yellow",
        "low": "white",
    }

    for lead in result:
        priority = lead.get("priority", "low")
        table.add_row(
            lead.get("business_name", "")[:30],
            lead.get("industry", "")[:15] if lead.get("industry") else "-",
            lead.get("location", "")[:20] if lead.get("location") else "-",
            lead.get("phone", "") or "-",
            f"{lead.get('score', 0):.1f}",
            f"[{priority_colors.get(priority, 'white')}]{priority}[/]",
            lead.get("status", "new"),
        )

    console.print(table)

    # Show signal details for hot leads
    if hot and result:
        console.print("\n[bold]Top Lead Details:[/bold]")
        top_lead = result[0]
        if "signals" in top_lead and top_lead["signals"]:
            for sig in top_lead["signals"][:3]:
                console.print(f"  • {sig.get('type', '')}: {sig.get('title', '')[:60]}")
                if sig.get("recommended_approach"):
                    console.print(f"    [dim]→ {sig['recommended_approach'][:80]}...[/dim]")


# === Export Commands ===


@app.command()
def export(
    format: str = typer.Option(
        "csv",
        "--format", "-f",
        help="Export format (csv, json, xlsx)",
    ),
    output: Optional[str] = typer.Option(
        None,
        "--output", "-o",
        help="Output file path (default: leads_YYYYMMDD.{format})",
    ),
    min_score: float = typer.Option(
        5,
        "--min-score",
        help="Minimum lead score",
    ),
    status: Optional[str] = typer.Option(
        None,
        "--status",
        help="Filter by status",
    ),
    limit: int = typer.Option(
        1000,
        "--limit",
        help="Maximum records to export",
    ),
):
    """
    Export leads for CRM import.

    Examples:
        deepscan export --format csv --min-score 7
        deepscan export --format xlsx -o leads.xlsx
    """
    from industry_deep_scan.database import BusinessRepository, SignalRepository, get_session
    from industry_deep_scan.models import LeadStatus

    if not output:
        date_str = datetime.now().strftime("%Y%m%d")
        output = f"leads_{date_str}.{format}"

    async def get_export_data():
        async with get_session() as session:
            repo = BusinessRepository(session)
            signal_repo = SignalRepository(session)

            lead_status = LeadStatus(status) if status else None

            businesses = await repo.get_leads(
                status=lead_status,
                min_score=min_score,
                limit=limit,
            )

            data = []
            for b in businesses:
                signals = await signal_repo.get_signals_by_business(b.id)
                top_signal = signals[0] if signals else None

                data.append({
                    "id": b.id,
                    "business_name": b.name,
                    "industry": b.industry or "",
                    "address": b.address or "",
                    "city": b.city or "",
                    "state": b.state or "",
                    "zip_code": b.zip_code or "",
                    "phone": b.phone or "",
                    "email": b.email or "",
                    "website": b.website or "",
                    "lead_score": b.lead_score,
                    "priority": b.priority.value,
                    "status": b.status.value,
                    "signal_type": top_signal.signal_type.value if top_signal else "",
                    "signal_title": top_signal.title if top_signal else "",
                    "recommended_approach": top_signal.recommended_approach if top_signal else "",
                    "source_url": top_signal.source_url if top_signal else "",
                    "created_at": b.created_at.isoformat(),
                })

            return data

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task("Fetching leads...", total=None)
        data = run_async(get_export_data())

    if not data:
        console.print("[yellow]No leads found matching criteria.[/yellow]")
        return

    # Export based on format
    if format == "csv":
        import csv

        with open(output, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=data[0].keys())
            writer.writeheader()
            writer.writerows(data)

    elif format == "json":
        import json

        with open(output, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    elif format == "xlsx":
        try:
            import pandas as pd

            df = pd.DataFrame(data)
            df.to_excel(output, index=False, engine="openpyxl")
        except ImportError:
            console.print("[red]Error: pandas/openpyxl required for xlsx export.[/red]")
            console.print("Install with: pip install pandas openpyxl")
            raise typer.Exit(1)

    else:
        console.print(f"[red]Unknown format: {format}[/red]")
        raise typer.Exit(1)

    console.print(f"[green]Exported {len(data)} leads to {output}[/green]")


# === Stats Commands ===


@app.command()
def stats(
    days: int = typer.Option(
        7,
        "--days", "-d",
        help="Analysis period in days",
    ),
):
    """
    Show scan and lead statistics.

    Examples:
        deepscan stats
        deepscan stats --days 30
    """
    from industry_deep_scan.engine import DeepScanEngine

    async def get_stats():
        async with DeepScanEngine() as engine:
            signal_stats = await engine.get_signal_stats(days)
            classifier_stats = await engine.get_classifier_stats()
            return signal_stats, classifier_stats

    signal_stats, classifier_stats = run_async(get_stats())

    # Signal stats panel
    console.print(Panel.fit(
        f"[bold]Signal Statistics (Last {days} days)[/bold]\n\n"
        f"Total Signals: [cyan]{signal_stats.get('total', 0)}[/cyan]\n",
        title="Stats",
    ))

    # By priority table
    if signal_stats.get("by_priority"):
        table = Table(title="Signals by Priority")
        table.add_column("Priority", style="cyan")
        table.add_column("Count", justify="right")

        for priority, count in signal_stats["by_priority"].items():
            table.add_row(str(priority), str(count))

        console.print(table)

    # By source table
    if signal_stats.get("by_source"):
        table = Table(title="Signals by Source")
        table.add_column("Source", style="cyan")
        table.add_column("Count", justify="right")

        for source, count in signal_stats["by_source"].items():
            table.add_row(str(source), str(count))

        console.print(table)

    # Classifier stats
    console.print(f"\n[bold]Classifier Stats:[/bold]")
    console.print(f"  Daily Cost: ${classifier_stats.get('daily_cost', 0):.4f}")
    console.print(f"  Cost Remaining: ${classifier_stats.get('cost_remaining', 0):.4f}")
    console.print(f"  Cache Size: {classifier_stats.get('cache_size', 0)}")


# === Server Commands ===


@app.command()
def serve(
    host: str = typer.Option(
        "0.0.0.0",
        "--host",
        help="Host to bind to",
    ),
    port: int = typer.Option(
        8000,
        "--port", "-p",
        help="Port to listen on",
    ),
    reload: bool = typer.Option(
        False,
        "--reload",
        help="Enable auto-reload for development",
    ),
):
    """
    Start the REST API server.

    Examples:
        deepscan serve
        deepscan serve --port 3000 --reload
    """
    import uvicorn

    console.print(f"[green]Starting API server on http://{host}:{port}[/green]")
    console.print("Press Ctrl+C to stop")

    uvicorn.run(
        "industry_deep_scan.api.main:app",
        host=host,
        port=port,
        reload=reload,
    )


@app.command()
def scheduler(
    foreground: bool = typer.Option(
        True,
        "--foreground/--background",
        help="Run in foreground or background",
    ),
):
    """
    Start the scan scheduler.

    Examples:
        deepscan scheduler
        deepscan scheduler --background
    """
    from industry_deep_scan.scheduler import run_scheduler

    console.print("[green]Starting scheduler...[/green]")
    console.print("Press Ctrl+C to stop")

    run_async(run_scheduler())


# === Utility Commands ===


@app.command()
def init():
    """
    Initialize the database and run first-time setup.
    """
    from industry_deep_scan.database import init_db

    console.print("[cyan]Initializing database...[/cyan]")

    run_async(init_db())

    console.print("[green]Database initialized successfully![/green]")
    console.print("\nNext steps:")
    console.print("  1. Configure your .env file with API keys")
    console.print("  2. Run a test scan: deepscan scan --source news --states CA")
    console.print("  3. View results: deepscan leads --hot")


@app.command()
def version():
    """Show version information."""
    from industry_deep_scan import __version__

    console.print(f"[bold]Industry Deep Scan[/bold] v{__version__}")


if __name__ == "__main__":
    app()
