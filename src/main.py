"""CLI entry point for Horizon."""

import argparse
import asyncio
from datetime import datetime, timezone
import sys
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console

from .orchestrator_factory import create_orchestrator
from .storage.manager import ConfigError, StorageManager


console = Console()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Horizon - AI-Driven Information Aggregation System"
        )
    )
    parser.add_argument(
        "--hours",
        type=int,
        help="Force fetch from last N hours",
    )
    parser.add_argument(
        "--since",
        help="FoodScope window start (RFC 3339 with offset)",
    )
    parser.add_argument(
        "--until",
        help="FoodScope window end (RFC 3339 with offset)",
    )
    parser.add_argument(
        "--no-deliver",
        action="store_true",
        help="Generate and archive without external delivery",
    )
    parser.add_argument(
        "--resume",
        metavar="RUN_ID",
        help="Resume a FoodScope run ID or 'latest'",
    )
    parser.add_argument(
        "--redeliver",
        action="store_true",
        help="Retry delivery while resuming",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run FoodScope on its configured schedule",
    )
    parser.add_argument(
        "--healthcheck",
        action="store_true",
        help="Validate config and scheduled-run freshness",
    )
    return parser


def parse_args(
    argv: list[str] | None = None,
) -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args(argv)
    has_explicit = (
        args.since is not None or args.until is not None
    )
    if (args.since is None) != (args.until is None):
        parser.error(
            "--since and --until must be provided together"
        )
    if args.hours is not None and has_explicit:
        parser.error(
            "--hours cannot be combined with --since/--until"
        )
    if args.resume and (
        args.hours is not None or has_explicit
    ):
        parser.error(
            "--resume cannot be combined with a manual window"
        )
    if args.redeliver and not args.resume:
        parser.error("--redeliver requires --resume")
    if args.redeliver and args.no_deliver:
        parser.error(
            "--redeliver cannot be combined with --no-deliver"
        )
    if args.daemon and (
        args.hours is not None
        or has_explicit
        or args.resume
        or args.redeliver
    ):
        parser.error(
            "--daemon cannot use manual windows or resume flags"
        )
    if args.healthcheck and (
        args.hours is not None
        or has_explicit
        or args.resume
        or args.redeliver
        or args.daemon
        or args.no_deliver
    ):
        parser.error(
            "--healthcheck cannot be combined with run flags"
        )
    return args


def print_banner():
    """Print the application banner."""
    banner = r"""
[bold blue]
  _    _            _
 | |  | |          (_)
 | |__| | ___  _ __ _ ___  ___  _ __
 |  __  |/ _ \| '__| |_  / / _ \| '_ \
 | |  | | (_) | |  | |/ / | (_) | | | |
 |_|  |_|\___/|_|  |_/___| \___/|_| |_|
[/bold blue]
[cyan]  AI-Driven Information Aggregation System[/cyan]
    """
    console.print(banner)


def main(argv: list[str] | None = None):
    """Main CLI entry point."""
    print_banner()

    args = parse_args(argv)

    try:
        # Load environment variables from .env file
        load_dotenv()

        # Ensure we're in the project directory or use data/ in current dir
        data_dir = Path("data")

        # Initialize storage manager
        storage = StorageManager(data_dir=str(data_dir))

        # Load configuration
        try:
            config = storage.load_config()
        except FileNotFoundError:
            console.print("[bold red]❌ Configuration file not found![/bold red]\n")
            data_dir_path = data_dir if isinstance(data_dir, Path) else Path(data_dir)
            example_path = data_dir_path / "config.example.json"
            if example_path.exists():
                console.print(
                    f"Copy the example config and edit it:\n"
                    f"  [cyan]cp {example_path} {data_dir_path / 'config.json'}[/cyan]\n"
                )
            console.print(
                "Or run [bold cyan]uv run horizon-wizard[/bold cyan] to launch the interactive setup wizard.\n"
            )
            sys.exit(1)
        except ConfigError as e:
            console.print(f"[bold red]❌ Error loading configuration: {e}[/bold red]")
            sys.exit(1)
        except Exception as e:
            console.print(f"[bold red]❌ Error loading configuration: {e}[/bold red]")
            sys.exit(1)

        foodscope_enabled = bool(
            config.foodscope is not None
            and config.foodscope.enabled
        )
        foodscope_flags = (
            args.since is not None
            or args.resume is not None
            or args.redeliver
            or args.daemon
            or args.no_deliver
            or args.healthcheck
        )
        if foodscope_flags and not foodscope_enabled:
            raise ValueError(
                "FoodScope CLI flags require foodscope.enabled"
            )

        if not foodscope_enabled:
            orchestrator = create_orchestrator(
                config, storage
            )
            asyncio.run(
                orchestrator.run(force_hours=args.hours)
            )
            return

        from .foodscope.retention import RetentionPolicy
        from .foodscope.scheduler import (
            FoodScopeScheduler,
            RunLock,
            RunLockHeldError,
            check_schedule_health,
        )

        scheduler = FoodScopeScheduler(
            timezone=config.schedule.timezone,
            cron=config.schedule.cron,
        )
        if args.healthcheck:
            # Construction validates profile/source packs and enabled
            # channel runtime configuration without making network calls.
            create_orchestrator(config, storage)
            health = check_schedule_health(
                Path(storage.data_dir) / "runs",
                scheduler,
                datetime.now(timezone.utc),
            )
            style = "green" if health.healthy else "red"
            console.print(
                f"[{style}]{health.detail}[/{style}]"
            )
            if not health.healthy:
                sys.exit(1)
            return

        async def run_foodscope_once(
            *, scheduled: bool = False
        ) -> None:
            orchestrator = create_orchestrator(
                config, storage
            )
            if args.resume is not None:
                await orchestrator.run(
                    deliver=args.redeliver,
                    resume_run_id=args.resume,
                )
            else:
                await orchestrator.run(
                    force_hours=args.hours,
                    since=args.since,
                    until=args.until,
                    deliver=not args.no_deliver,
                )
            if scheduled:
                RetentionPolicy().apply(
                    Path(storage.data_dir) / "runs",
                    datetime.now(timezone.utc),
                )

        lock = RunLock(
            Path(storage.data_dir)
            / "state"
            / "foodscope.lock"
        )
        try:
            with lock:
                if args.daemon:
                    asyncio.run(
                        scheduler.run_forever(
                            lambda: run_foodscope_once(
                                scheduled=True
                            )
                        )
                    )
                else:
                    asyncio.run(run_foodscope_once())
        except RunLockHeldError as error:
            console.print(f"[yellow]{error}[/yellow]")
            sys.exit(error.exit_code)

    except KeyboardInterrupt:
        console.print("\n[yellow]⚠️  Interrupted by user[/yellow]")
        sys.exit(0)
    except Exception as e:
        console.print(f"\n[bold red]❌ Fatal error: {e}[/bold red]")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def print_config_template():
    """Print configuration template."""
    template = """
{
  "version": "1.0",
  "ai": {
    "provider": "anthropic",
    "model": "claude-sonnet-4.5-20250929",
    "api_key_env": "ANTHROPIC_API_KEY",
    "temperature": 0.3,
    "max_tokens": 4096
  },
  "sources": {
    "github": [
      {
        "type": "user_events",
        "username": "torvalds",
        "enabled": true
      }
    ],
    "hackernews": {
      "enabled": true,
      "fetch_top_stories": 30,
      "min_score": 100
    },
    "rss": [
      {
        "name": "Example Blog",
        "url": "https://example.com/feed.xml",
        "enabled": true,
        "category": "software-engineering"
      }
    ]
  },
  "filtering": {
    "ai_score_threshold": 7.0,
    "time_window_hours": 24,
    "max_items": null,
    "category_groups": {},
    "default_group": "other",
    "default_group_limit": null
  }
}

Also create a .env file with:
ANTHROPIC_API_KEY=your_api_key_here
GITHUB_TOKEN=your_github_token_here (optional but recommended)
"""
    console.print(template)


if __name__ == "__main__":
    main()
