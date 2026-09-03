#!/usr/bin/env python3
"""
Metis — Autonomous Username OSINT Reconnaissance Tool
Dual Mode: Interactive Command-Line Interface (CLI) & Web Service
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.text import Text

from core.engine import UsernameSearchEngine
from core.models import CheckStatus, EventType
from core.reporter import generate_html_report

console = Console()

BANNER = r"""[bold purple]
 __  __      _   _     
|  \/  | ___| |_(_)___ 
| |\/| |/ _ \ __| / __|
| |  | |  __/ |_| \__ \
|_|  |_|\___|\__|_|___/
[/bold purple][dim]Autonomous Username OSINT Engine[/dim]
"""


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


async def run_cli_search(
    username: str,
    categories: Optional[List[str]] = None,
    priority_sites: Optional[List[str]] = None,
    extract_profile: bool = True,
    include_duckduckgo: bool = False,
    concurrency: int = 30,
    timeout: int = 10,
    html_output: Optional[str] = None,
    json_output: Optional[str] = None,
):
    ddg_slider = (
        "[bold green]● ON [/bold green][bold purple][━━━━━━●][/bold purple] [dim](deep web search)[/dim]"
        if include_duckduckgo
        else "[dim]○ OFF [●━━━━━━] (enable with --ddg)[/dim]"
    )

    console.print(BANNER)
    console.print(
        Panel(
            f"[bold white]Target Username:[/bold white] [bold cyan]@{username}[/bold cyan]\n"
            f"[bold white]DuckDuckGo Scan:[/bold white] {ddg_slider}\n"
            f"[bold white]Profile Data:[/bold white]    [green]{'Enabled' if extract_profile else 'Disabled'}[/green]   "
            f"[bold white]Concurrency:[/bold white] {concurrency}   "
            f"[bold white]Timeout:[/bold white] {timeout}s",
            title="[bold purple]Scan Configuration[/bold purple]",
            border_style="purple",
        )
    )

    engine = UsernameSearchEngine(
        max_concurrent_requests=concurrency,
        timeout_seconds=timeout,
    )

    found_results = []
    profile_data_map = {}
    completed_stats = {}
    total_sites = 0

    progress = Progress(
        SpinnerColumn(spinner_name="dots", style="purple"),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=40, style="grey30", complete_style="purple"),
        TaskProgressColumn(),
        TextColumn("[bold cyan]{task.completed}/{task.total}[/bold cyan] sites"),
        TextColumn("[bold green]{task.fields[found]}[/bold green] found"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    )

    with progress:
        task_id = progress.add_task(
            f"[bold purple]Scanning @{username}...[/bold purple]",
            total=1,
            found=0,
        )

        async for event in engine.stream_search(
            username=username,
            include_duckduckgo=include_duckduckgo,
            extract_profile=extract_profile,
            categories=categories,
            priority_sites=priority_sites,
        ):
            if event.event_type == EventType.SEARCH_STARTED:
                total_sites = event.data.get("total_sites", 1)
                progress.update(task_id, total=total_sites)

            elif event.event_type == EventType.DUCKDUCKGO_STARTED:
                progress.console.print(
                    "  [bold yellow]🦆[/bold yellow] [dim]Starting DuckDuckGo web search in parallel...[/dim]"
                )

            elif event.event_type == EventType.DUCKDUCKGO_RESULT:
                url = event.data.get("url", "")
                domain = event.data.get("domain", "DuckDuckGo")
                title = event.data.get("title", "")
                ddg_result = {
                    "site_name": domain,
                    "category": "search engine",
                    "url": url,
                    "status": CheckStatus.FOUND.value,
                    "profile_data": {
                        "title": title,
                        "source": "DuckDuckGo Search",
                    },
                }
                found_results.append(ddg_result)
                progress.console.print(
                    f"  [bold yellow]🦆 [DDG][/bold yellow] [bold white]{domain}[/bold white] "
                    f"([dim]search engine[/dim]) ──> [cyan]{url}[/cyan]"
                )
                if title:
                    progress.console.print(
                        f"      [dim]↳[/dim] [yellow]{title}[/yellow]"
                    )

            elif event.event_type == EventType.SITE_RESULT:
                progress_info = event.data.get("progress")
                if progress_info:
                    progress.update(
                        task_id,
                        completed=progress_info["checked"],
                        total=progress_info["total"],
                        found=progress_info["found"],
                    )

                if event.data.get("status") == CheckStatus.FOUND.value:
                    found_results.append(event.data)
                    site_name = event.data.get("site_name", "Unknown")
                    cat = event.data.get("category", "general")
                    url = event.data.get("url", "")

                    progress.console.print(
                        f"  [bold green][+][/bold green] [bold white]{site_name}[/bold white] "
                        f"([dim]{cat}[/dim]) ──> [cyan]{url}[/cyan]"
                    )

            elif event.event_type == EventType.PROFILE_EXTRACTED:
                site_name = event.data.get("site_name")
                url = event.data.get("url")
                pdata = event.data.get("profile_data", {})
                profile_data_map[(site_name, url)] = pdata

                # Print brief extracted metadata
                details = []
                if "fullname" in pdata or "name" in pdata:
                    name = pdata.get("fullname") or pdata.get("name")
                    details.append(f"Name: [bold]{name}[/bold]")
                if "followers" in pdata or "follower_count" in pdata:
                    followers = pdata.get("followers") or pdata.get("follower_count")
                    details.append(f"Followers: [bold]{followers}[/bold]")
                if "location" in pdata or "country" in pdata:
                    loc = pdata.get("location") or pdata.get("country")
                    details.append(f"Location: [bold]{loc}[/bold]")

                if details:
                    progress.console.print(
                        f"      [dim]↳[/dim] [magenta]{' | '.join(details)}[/magenta]"
                    )

            elif event.event_type == EventType.SEARCH_COMPLETED:
                completed_stats = event.data

    # Merge profile data
    for item in found_results:
        key = (item.get("site_name"), item.get("url"))
        if key in profile_data_map:
            item["profile_data"] = profile_data_map[key]

    # Display final Results Table
    console.print()
    if found_results:
        table = Table(
            title=f"[bold]Discovered Accounts for @{username} ({len(found_results)} total)[/bold]",
            border_style="purple",
            header_style="bold purple",
            show_lines=True,
        )
        table.add_column("#", style="dim", width=4)
        table.add_column("Platform", style="bold white", width=22)
        table.add_column("Category", style="cyan", width=14)
        table.add_column("Profile URL", style="blue")
        table.add_column("Profile Data", style="dim", width=25)

        for i, item in enumerate(found_results, 1):
            pdata = item.get("profile_data") or {}
            preview_items = []
            if "fullname" in pdata or "name" in pdata:
                preview_items.append(f"Name: {pdata.get('fullname') or pdata.get('name')}")
            if "followers" in pdata or "follower_count" in pdata:
                preview_items.append(f"Followers: {pdata.get('followers') or pdata.get('follower_count')}")
            preview_str = ", ".join(preview_items) if preview_items else ("Rich data available" if pdata else "None")

            table.add_row(
                str(i),
                item.get("site_name", ""),
                item.get("category", ""),
                item.get("url", ""),
                preview_str,
            )

        console.print(table)
    else:
        console.print(
            Panel(
                f"[yellow]No accounts found matching username @{username}[/yellow]",
                title="Results",
                border_style="yellow",
            )
        )

    # Summary Panel
    elapsed = completed_stats.get("search_time_seconds", 0)
    scanned = completed_stats.get("total_checked", total_sites)
    found_count = len(found_results)
    rate = completed_stats.get("success_rate", 0)

    summary_text = (
        f"[bold]Scanned Platforms:[/bold] {scanned} | "
        f"[bold green]Accounts Found:[/bold green] {found_count} | "
        f"[bold]Duration:[/bold] {elapsed}s | "
        f"[bold]Hit Rate:[/bold] {rate}%"
    )
    console.print(Panel(summary_text, title="[bold purple]Search Summary[/bold purple]", border_style="purple"))

    # Save to JSON if requested
    if json_output:
        json_path = Path(json_output)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "username": username,
                    "stats": completed_stats,
                    "results": found_results,
                },
                f,
                indent=2,
            )
        console.print(f"[bold green]✓[/bold green] Saved JSON output to: [cyan]{json_path.resolve()}[/cyan]")

    # Save to HTML Report if requested
    if html_output:
        report_path = generate_html_report(
            username=username,
            results=found_results,
            stats=completed_stats,
            output_path=html_output,
        )
        console.print(f"[bold green]✓[/bold green] Saved styled HTML report to: [bold cyan]{report_path}[/bold cyan]")
        console.print("[dim]You can open this HTML file directly in any web browser to view the interactive dashboard.[/dim]")


def start_web_server(host: str = "0.0.0.0", port: int = 8000, reload: bool = False):
    import uvicorn

    console.print(BANNER)
    console.print(
        Panel(
            f"[bold green]Starting Metis Web Service[/bold green]\n\n"
            f"[bold white]Web Interface:[/bold white] [cyan]http://{host if host != '0.0.0.0' else 'localhost'}:{port}[/cyan]\n"
            f"[bold white]Swagger API:[/bold white]   [cyan]http://{host if host != '0.0.0.0' else 'localhost'}:{port}/docs[/cyan]",
            title="[bold purple]Metis Server[/bold purple]",
            border_style="purple",
        )
    )
    uvicorn.run("web.app:app", host=host, port=port, reload=reload)


def main():
    parser = argparse.ArgumentParser(
        description="Metis — Autonomous Username OSINT Intelligence (CLI & Web Service)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Mode selection
    parser.add_argument(
        "username",
        nargs="?",
        help="Username to investigate across platforms (CLI mode)",
    )
    parser.add_argument(
        "--web",
        "--serve",
        action="store_true",
        help="Launch the standalone Metis web service",
    )

    # Web service options
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Web server binding host (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Web server port (default: 8000)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development",
    )

    # CLI search options
    parser.add_argument(
        "-o",
        "--output",
        help="Save output file. If ending in .html, saves HTML report; if .json, saves JSON",
    )
    parser.add_argument(
        "--html",
        help="Explicitly save interactive, styled HTML report to given file path",
    )
    parser.add_argument(
        "--json",
        help="Save raw scan results as a JSON file",
    )
    parser.add_argument(
        "-c",
        "--category",
        help="Filter platforms by category (comma-separated, e.g. social,developer,gaming)",
    )
    parser.add_argument(
        "--no-extract",
        action="store_true",
        help="Disable deep profile data extraction via socid-extractor",
    )
    parser.add_argument(
        "--ddg",
        action="store_true",
        help="Include DuckDuckGo web search results",
    )
    parser.add_argument(
        "-t",
        "--concurrency",
        type=int,
        default=30,
        help="Maximum concurrent HTTP requests (default: 30)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=10,
        help="Per-site HTTP timeout in seconds (default: 10)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose debug logging",
    )

    args = parser.parse_args()
    setup_logging(args.verbose)

    # Check if web mode requested
    if args.web or (not args.username and len(sys.argv) == 1):
        # Default with no args or --web is starting web service, or prompt help
        if not args.username and not args.web:
            parser.print_help()
            sys.exit(0)
        start_web_server(host=args.host, port=args.port, reload=args.reload)
        return

    if not args.username:
        console.print("[bold red]Error:[/bold red] Username is required for CLI search. Run with --help for usage.")
        sys.exit(1)

    # Determine report outputs
    html_out = args.html
    json_out = args.json

    if args.output:
        if args.output.lower().endswith(".html"):
            html_out = args.output
        elif args.output.lower().endswith(".json"):
            json_out = args.output
        else:
            # Default to HTML report
            html_out = f"{args.output}.html"

    categories = [c.strip() for c in args.category.split(",")] if args.category else None

    asyncio.run(
        run_cli_search(
            username=args.username,
            categories=categories,
            extract_profile=not args.no_extract,
            include_duckduckgo=args.ddg,
            concurrency=args.concurrency,
            timeout=args.timeout,
            html_output=html_out,
            json_output=json_out,
        )
    )


if __name__ == "__main__":
    main()
