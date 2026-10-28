#!/usr/bin/env python3
"""Call the service's MCP tools from a shell — for a session without the MCP server
attached. Same endpoint, same tools, same text back. Stdlib only.

    scripts/srs.py --tools                              # instructions + every tool's doc
    scripts/srs.py get_state '{"initiative": "order-events"}'
    scripts/srs.py write @ops.json                      # arguments from a file
    scripts/srs.py drift_report '{"initiative": "order-events", "task": "T-1", "format": "markdown"}'

Who you are: $SRS_ACTOR (default $USER), sent as X-Actor; MCP callers are agents.
"""

import getpass
import json
import os
import sys
import urllib.request

URL = os.environ.get("SRS_URL", "http://localhost:8791/mcp")
ACTOR = os.environ.get("SRS_ACTOR") or getpass.getuser()


def rpc(method: str, params: dict) -> dict:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    request = urllib.request.Request(
        URL,
        data=body.encode(),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "X-Actor": ACTOR,
            "X-Actor-Kind": "agent",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def main(argv) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "--tools":
        init = rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "srs.py", "version": "1"}})
        print(init["result"].get("instructions", ""), "\n")
        for tool in rpc("tools/list", {})["result"]["tools"]:
            print(f"## {tool['name']}\n{tool.get('description', '').strip()}\n")
        return 0
    name, raw = argv[0], (argv[1] if len(argv) > 1 else "{}")
    if raw.startswith("@"):
        raw = open(raw[1:]).read()
    out = rpc("tools/call", {"name": name, "arguments": json.loads(raw)})
    if "error" in out:
        print(out["error"].get("message"), file=sys.stderr)
        return 1
    result = out["result"]
    text = "\n".join(c.get("text", "") for c in result.get("content", []))
    print(text)
    return 1 if result.get("isError") else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
