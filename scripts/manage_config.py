#!/usr/bin/env python3
"""
Manage the per-user connector config for the unified-communication skill.

Config lives at ~/.unified-communication/connectors.json. This script is a
plain filesystem operation (no MCP dependency), so it's safe to call from
Bash directly.

Usage:
  manage_config.py --show
  manage_config.py --init '{"gmail": {"status": "live", "access": "mcp", "notes": ""}, ...}'
  manage_config.py --add gong --status planned --access api --notes "Needs Gong API key with transcript scope"
  manage_config.py --add salesforce --status live --access mcp --may-duplicate gmail,gong --notes "Einstein Activity Capture syncs Gmail + Gong calls in as activities"
  manage_config.py --remove gong

--may-duplicate is optional and only makes sense for a source (typically a CRM) that
re-stores communication already reachable through another live source. It's a plain
list of other connector names to check for overlap against when answering a query
(see references/catalog.md's "Watch for duplicates" note) -- it doesn't change access
or status.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

CONFIG_DIR = os.path.expanduser("~/.unified-communication")
CONFIG_PATH = os.path.join(CONFIG_DIR, "connectors.json")

VALID_STATUS = {"live", "planned"}
VALID_ACCESS = {"mcp", "api", "manual"}


def load_config():
    if not os.path.exists(CONFIG_PATH):
        return None
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def save_config(config):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    config["last_updated"] = datetime.now(timezone.utc).isoformat()
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")


def cmd_show(_args):
    config = load_config()
    if config is None:
        print(json.dumps({"exists": False}, indent=2))
        return
    print(json.dumps(config, indent=2))


def cmd_init(args):
    try:
        connectors = json.loads(args.init)
    except json.JSONDecodeError as e:
        print(f"Error: --init value must be valid JSON: {e}", file=sys.stderr)
        sys.exit(1)

    for name, spec in connectors.items():
        _validate_spec(name, spec)

    config = {"version": 1, "connectors": connectors}
    save_config(config)
    print(f"Initialized config at {CONFIG_PATH}")
    print(json.dumps(config, indent=2))


def cmd_add(args):
    if not args.status or not args.access:
        print("Error: --add requires --status and --access", file=sys.stderr)
        sys.exit(1)

    spec = {
        "status": args.status,
        "access": args.access,
        "notes": args.notes or "",
    }
    if args.may_duplicate:
        spec["may_duplicate"] = [name.strip() for name in args.may_duplicate.split(",") if name.strip()]
    _validate_spec(args.add, spec)

    config = load_config() or {"version": 1, "connectors": {}}
    config["connectors"][args.add] = spec
    save_config(config)
    print(f"Added/updated connector '{args.add}'")
    print(json.dumps(config, indent=2))


def cmd_remove(args):
    config = load_config()
    if config is None or args.remove not in config.get("connectors", {}):
        print(f"'{args.remove}' is not in the config; nothing to remove.")
        return
    del config["connectors"][args.remove]
    save_config(config)
    print(f"Removed connector '{args.remove}'")
    print(json.dumps(config, indent=2))


def _validate_spec(name, spec):
    status = spec.get("status")
    access = spec.get("access")
    if status not in VALID_STATUS:
        print(f"Error: connector '{name}' has invalid status '{status}' "
              f"(must be one of {sorted(VALID_STATUS)})", file=sys.stderr)
        sys.exit(1)
    if access not in VALID_ACCESS:
        print(f"Error: connector '{name}' has invalid access '{access}' "
              f"(must be one of {sorted(VALID_ACCESS)})", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--show", action="store_true", help="Print the current config (or {\"exists\": false} if none)")
    group.add_argument("--init", metavar="JSON", help="Create/overwrite the config with this connectors JSON object")
    group.add_argument("--add", metavar="NAME", help="Add or update one connector")
    group.add_argument("--remove", metavar="NAME", help="Remove one connector")

    parser.add_argument("--status", choices=sorted(VALID_STATUS), help="Required with --add")
    parser.add_argument("--access", choices=sorted(VALID_ACCESS), help="Required with --add")
    parser.add_argument("--notes", default="", help="Optional free-text note, e.g. what setup a planned connector still needs")
    parser.add_argument("--may-duplicate", default="", metavar="NAME[,NAME...]",
                         help="Comma-separated connector names this one may double-count communication with (e.g. a CRM that syncs email/calls in as activities)")

    args = parser.parse_args()

    if args.show:
        cmd_show(args)
    elif args.init:
        cmd_init(args)
    elif args.add:
        cmd_add(args)
    elif args.remove:
        cmd_remove(args)


if __name__ == "__main__":
    main()
