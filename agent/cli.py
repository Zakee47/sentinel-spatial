"""Command-line interface for Sentinel mission sessions."""

import argparse
import json
import os
import sys

from agent.sentinel_agent import DevinAPIError, launch, list_runs, status, wait


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch a Sentinel mission planner")
    parser.add_argument("goal", nargs="?")
    parser.add_argument("--api-base", default="http://localhost:8000")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--list", action="store_true")
    group.add_argument("--status", metavar="SESSION_ID")
    parser.add_argument("--wait", action="store_true", help="wait for a mock simulation")
    args = parser.parse_args()
    try:
        if args.list:
            print(json.dumps(list_runs(), indent=2))
        elif args.status:
            print(json.dumps(status(args.status), indent=2))
        else:
            if not args.goal:
                parser.error("goal is required unless using --list or --status")
            if args.wait and os.environ.get("SENTINEL_AGENT_MOCK") != "1":
                parser.error("--wait is supported in mock mode only")
            run = launch(args.goal, args.api_base)
            print(run["url"], flush=True)
            if args.wait:
                result = wait(run["session_id"])
                print(json.dumps(result, indent=2))
                if result["status"] == "failed":
                    return 1
    except (DevinAPIError, ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
