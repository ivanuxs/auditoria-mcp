#!/usr/bin/env bash
# Cierra el proxy con token y el servidor MCP de auditoría de este proyecto.
#
# Solo toca los procesos que escuchan en los puertos del `.env`: si otro programa
# tuviera esos puertos, se cierra ese, que es justo lo que hay que liberar para
# poder volver a arrancar. Primero el proxy (corta la puerta), después el interno.
set -uo pipefail
cd "$(dirname "$0")"

INTERNO=$(grep -E '^MCP_INTERNO_PUERTO=' .env 2>/dev/null | cut -d= -f2 | tr -d ' \r')
INTERNO=${INTERNO:-8940}
PUERTO=$(grep -E '^MCP_PROXY_PUERTO=' .env 2>/dev/null | cut -d= -f2 | tr -d ' \r')
PUERTO=${PUERTO:-8941}

# PIDs que escuchan en un puerto (los del usuario, así que `ss` muestra el pid).
pids_del_puerto() {
    ss -ltnpH "sport = :$1" 2>/dev/null | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u
}

cerrar() {
    local puerto=$1 nombre=$2 pids
    pids=$(pids_del_puerto "$puerto")
    if [[ -z "$pids" ]]; then
        echo "· ${nombre}: nada escuchando en ${puerto}."
        return 0
    fi

    echo "· ${nombre}: cerrando pid(s) ${pids//$'\n'/ } (puerto ${puerto})…"
    # shellcheck disable=SC2086  # se quiere dividir por líneas
    kill $pids 2>/dev/null || true

    for _ in $(seq 1 20); do
        if [[ -z "$(pids_del_puerto "$puerto")" ]]; then
            echo "✔ ${nombre} cerrado."
            return 0
        fi
        sleep 0.25
    done

    echo "· ${nombre} no cerró solo; se fuerza."
    # shellcheck disable=SC2086
    kill -9 $pids 2>/dev/null || true
}

cerrar "$PUERTO" "proxy"
cerrar "$INTERNO" "MCP"
