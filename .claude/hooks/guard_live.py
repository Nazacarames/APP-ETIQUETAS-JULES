#!/usr/bin/env python3
"""Hook PreToolUse de Claude Code: impide que el agente active dinero real o lea secretos.

Claude Code le pasa por stdin un JSON con tool_input.command. Si salimos con
código 2, el comando se bloquea y el mensaje de stderr le llega a Claude.
"""
import json
import re
import sys

BLOCKS = [
    (r"LIVE_TRADING\s*=\s*['\"]?(1|true|yes|on|si)", "Activar LIVE_TRADING es una decisión humana, no del agente."),
    (r"api\.alpaca\.markets", "El agente no puede apuntar a la API de dinero real de Alpaca."),
    (r"live\s*=\s*True", "El agente no puede instanciar brokers en modo real."),
    (r"(^|[\s/'\"=<])\.env(\s|$|['\"])", "El agente no lee ni modifica .env (contiene API keys)."),
]


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return
    command = str(payload.get("tool_input", {}).get("command", ""))
    for pattern, message in BLOCKS:
        if re.search(pattern, command, re.IGNORECASE):
            print(f"Bloqueado por guard_live.py: {message}", file=sys.stderr)
            sys.exit(2)


if __name__ == "__main__":
    main()
