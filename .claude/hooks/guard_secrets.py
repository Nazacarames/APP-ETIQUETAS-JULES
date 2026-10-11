#!/usr/bin/env python3
"""Hook PreToolUse de Claude Code: el agente no lee secretos, no opera y no automatiza casas de apuestas.

Polylens y el analista de fútbol solo analizan datos. Bloquea comandos que lean .env, que
intenten firmar u operar en Polymarket (bloqueado en Argentina desde marzo de 2026) o que
accedan en forma automática a bet365 (sus reglas lo prohíben). Salir con código 2 bloquea
el comando y el mensaje le llega a Claude.
"""
import json
import re
import sys

BLOCKS = [
    (r"(^|[\s/'\"=<])\.env(\s|$|['\"])", "El agente no lee ni modifica .env (contiene claves)."),
    (r"clob\.polymarket\.com/(order|orders|auth)", "Polylens solo analiza: no envía órdenes a Polymarket."),
    (r"py[-_]clob[-_]client|clob-client", "Polylens solo analiza: no instala ni usa clientes de órdenes."),
    (r"PRIVATE_KEY", "Polylens no maneja claves privadas de billeteras."),
    (r"(curl|wget|requests|urllib|playwright|selenium|chromium)\b.*bet365\.",
     "bet365 prohíbe el acceso automático: sus cuotas se cargan a mano o llegan por API-Football."),
]


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return
    command = str(payload.get("tool_input", {}).get("command", ""))
    for pattern, message in BLOCKS:
        if re.search(pattern, command, re.IGNORECASE):
            print(f"Bloqueado por guard_secrets.py: {message}", file=sys.stderr)
            sys.exit(2)


if __name__ == "__main__":
    main()
