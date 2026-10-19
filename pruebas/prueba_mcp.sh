#!/usr/bin/env bash
# Prueba del proxy: sin token debe dar 401; con token, el MCP debe contestar.
set -uo pipefail
cd "$(dirname "$0")/.."

PUERTO=$(grep -E '^MCP_PROXY_PUERTO=' .env | cut -d= -f2 | tr -d ' \r'); PUERTO=${PUERTO:-8941}
TOKEN=$(grep -E '^MCP_TOKEN=' .env | cut -d= -f2 | tr -d ' \r')
TOKEN_NODIT=$(grep -E '^MCP_TOKEN_NODIT=' .env | cut -d= -f2 | tr -d ' \r')

CUERPO='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"prueba","version":"1.0"}}}'

echo "== 1) sin token (debe dar 401) =="
curl -s -o /dev/null -w "HTTP %{http_code}\n" -m 20 \
    -X POST "http://127.0.0.1:${PUERTO}/mcp" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -d "$CUERPO"

echo "== 2) con token (debe dar 200 y un JSON-RPC) =="
curl -s -m 30 -w "\nHTTP %{http_code}\n" \
    -X POST "http://127.0.0.1:${PUERTO}/mcp" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -H "Authorization: Bearer ${TOKEN}" \
    -d "$CUERPO" | head -c 600

echo "== 3) con token de Nodit (debe dar 200) =="
if [[ -z "$TOKEN_NODIT" ]]; then
    echo "· Sin MCP_TOKEN_NODIT en el .env: se omite."
else
    curl -s -o /dev/null -m 30 -w "HTTP %{http_code}\n" \
        -X POST "http://127.0.0.1:${PUERTO}/mcp" \
        -H "Content-Type: application/json" \
        -H "Accept: application/json, text/event-stream" \
        -H "Authorization: Bearer ${TOKEN_NODIT}" \
        -d "$CUERPO"
fi

echo "== 4) ningún token aparece en claro en los registros =="
FALLO=0
for VALOR in "$TOKEN" "$TOKEN_NODIT"; do
    [[ -z "$VALOR" ]] && continue
    if grep -qF -- "$VALOR" logs/*.txt 2>/dev/null; then
        echo "✘ FALLO: un token aparece en claro en los registros."
        FALLO=1
    fi
done
if [[ "$FALLO" -eq 0 ]]; then
    echo "✔ Ningún token aparece en claro."
fi
