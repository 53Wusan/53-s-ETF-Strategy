from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .research import run_strict_research


def _strict_research(args: argparse.Namespace) -> int:
    result = run_strict_research(args.config, refresh=args.refresh)
    decision = result["decision"]
    print(json.dumps({
        "decision": decision["decision"],
        "reason": decision["reason"],
        "data_gate": decision["data_gate"]["status"],
        "report": result["report_path"],
        "manifest": result["manifest_path"],
    }, ensure_ascii=False, indent=2))
    return 0


def _signal(args: argparse.Namespace) -> int:
    result = run_strict_research(args.config, refresh=args.refresh)
    output_dir = Path("outputs/v0_2")
    signals = sorted((output_dir / "signals").glob("research_preview_signal_*.json"))
    if not signals:
        print("No signal artifact was generated.", file=sys.stderr)
        return 2
    print(signals[-1])
    return 0


def _web(args: argparse.Namespace) -> int:
    decision_path = Path(args.decision)
    if not decision_path.exists():
        print("Run strict-research before requesting the web UI.", file=sys.stderr)
        return 2
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    if decision.get("decision") != "PAPER_TRACK":
        print(
            "Web UI remains locked because no strategy passed the strict data and performance gates.",
            file=sys.stderr,
        )
        return 3
    app_path = Path("app/streamlit_app.py")
    if not app_path.exists():
        print("Gate passed, but the web UI has not yet been scaffolded.", file=sys.stderr)
        return 4
    return subprocess.call([sys.executable, "-m", "streamlit", "run", str(app_path)])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="money-back")
    subparsers = parser.add_subparsers(dest="command", required=True)
    research = subparsers.add_parser("strict-research", help="Run the preregistered V0.2 study")
    research.add_argument("--config", default="configs/t5_v0_2.json")
    research.add_argument("--refresh", action="store_true")
    research.set_defaults(handler=_strict_research)
    signal = subparsers.add_parser("signal", help="Generate a research-only signal preview")
    signal.add_argument("--config", default="configs/t5_v0_2.json")
    signal.add_argument("--refresh", action="store_true")
    signal.set_defaults(handler=_signal)
    web = subparsers.add_parser("web", help="Launch the gated local web UI")
    web.add_argument("--decision", default="outputs/v0_2/decision.json")
    web.set_defaults(handler=_web)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
