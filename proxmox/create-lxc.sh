#!/usr/bin/env bash
# ===========================================================================
#  ImmichHelper – legt auf dem Proxmox-Host einen LXC-Container an und installiert ImmichHelper darin.
#
#  Auf dem Proxmox-Server als root (z. B. Rechenzentrum → Knoten → Shell):
#    bash -c "$(curl -fsSL https://raw.githubusercontent.com/Tillhnz/ImmichHelper/main/proxmox/create-lxc.sh)"
#
#  Läuft ImmichHelper schon, bietet dasselbe Skript das Update an.
#
#  Anpassen per Umgebungsvariablen (alle optional), z. B.:
#    CTID=151 IMMICH_URL=http://192.168.1.20:2283 bash -c "$(curl -fsSL …/create-lxc.sh)"
#
#    CTID=<frei>            Container-ID (Standard: nächste freie)
#    CT_HOSTNAME=immichhelper
#    STORAGE=<auto>         Speicher für die Container-Festplatte (local-lvm, local-zfs, …)
#    TEMPLATE_STORAGE=local
#    DEBIAN=12              Debian-Version der Vorlage (12 oder 13)
#    DISK_GB=4  CORES=2  MEMORY_MB=1024
#    BRIDGE=vmbr0  IP=dhcp  GW=  VLAN=
#    PORT=8080              Port der Oberfläche
#    IMMICH_URL=            Adresse von Immich (sonst wird gesucht bzw. gefragt)
#    NTFY_TOPIC=            ntfy-Thema für Push-Nachrichten bei Updates (wie bei den anderen Helpern)
#    NONINTERACTIVE=1       keine Rückfragen
#
#  ImmichHelper braucht keinen Zugriff auf die NAS: Es arbeitet nur über die Immich-API.
# ===========================================================================
set -euo pipefail

REPO="${IH_REPO:-Tillhnz/ImmichHelper}"
BRANCH="${IH_BRANCH:-main}"
RAW="https://raw.githubusercontent.com/${REPO}/${BRANCH}"

C_OK=$'\e[1;32m'; C_ERR=$'\e[1;31m'; C_INFO=$'\e[1;36m'; C_DIM=$'\e[2m'; C_WARN=$'\e[1;33m'; C_OFF=$'\e[0m'
step() { echo "${C_INFO}›${C_OFF} $*"; }
ok()   { echo "${C_OK}✔${C_OFF} $*"; }
warn() { echo "${C_WARN}!${C_OFF} $*"; }
die()  { echo "${C_ERR}✘ $*${C_OFF}" >&2; exit 1; }

TTY=""
if [[ -z "${NONINTERACTIVE:-}" ]]; then
  if [[ -t 0 ]]; then TTY=/dev/stdin; elif (exec </dev/tty) 2>/dev/null; then TTY=/dev/tty; fi
fi
ask() { # Frage, Standard
  local a=""
  if [[ -n "$TTY" ]]; then read -r -p "$1 [$2]: " a <"$TTY" || a=""; fi
  printf '%s' "${a:-$2}"
}

command -v pct >/dev/null 2>&1 || die "Dieses Skript läuft auf dem Proxmox-Host (pct nicht gefunden)."
[[ $EUID -eq 0 ]] || die "Bitte als root ausführen."

echo
echo "  ${C_INFO}ImmichHelper${C_OFF} ${C_DIM}– Fotos in Immich aussortieren und ordnen, als Container auf Proxmox${C_OFF}"
echo

# ---------------------------------------------------------------------------
# Gibt es schon einen ImmichHelper-Container? → Update anbieten
# ---------------------------------------------------------------------------
EXISTING=""
for conf in /etc/pve/lxc/*.conf; do
  [[ -f "$conf" ]] || continue
  if grep -qE '^tags:.*\bimmichhelper\b' "$conf"; then EXISTING="$(basename "$conf" .conf)"; break; fi
done
if [[ -n "$EXISTING" && -z "${CTID:-}" ]]; then
  echo "  Es gibt schon einen ImmichHelper-Container: ${C_INFO}#${EXISTING}${C_OFF} ($(pct config "$EXISTING" | awk '/^hostname:/{print $2}'))"
  a="$(ask "  Diesen aktualisieren? (j = aktualisieren, n = zusätzlich einen neuen anlegen)" "j")"
  if [[ "$a" =~ ^[jJyY]$ ]]; then
    pct status "$EXISTING" | grep -q running || { step "Starte Container #$EXISTING …"; pct start "$EXISTING"; sleep 5; }
    step "Aktualisiere ImmichHelper in #$EXISTING …"
    pct exec "$EXISTING" -- bash -c "command -v immichhelper >/dev/null && immichhelper update || bash /opt/immichhelper/install.sh --update"
    exit 0
  fi
fi

# ---------------------------------------------------------------------------
# Immich suchen: Container oder VM mit „immich“ im Namen, Port 2283
# ---------------------------------------------------------------------------
IMMICH_URL="${IMMICH_URL:-}"
if [[ -z "$IMMICH_URL" ]]; then
  step "Suche Immich auf diesem Server …"
  for conf in /etc/pve/lxc/*.conf; do
    [[ -f "$conf" ]] || continue
    id="$(basename "$conf" .conf)"
    if grep -qiE '^(hostname|tags):.*immich' "$conf" && ! grep -qE '^tags:.*\bimmichhelper\b' "$conf"; then
      ip="$(pct exec "$id" -- hostname -I 2>/dev/null | awk '{print $1}' || true)"
      [[ -n "$ip" ]] && curl -fs -m 4 "http://${ip}:2283/api/server/ping" >/dev/null 2>&1 && { IMMICH_URL="http://${ip}:2283"; break; }
    fi
  done
  if [[ -z "$IMMICH_URL" ]] && command -v qm >/dev/null; then
    for conf in /etc/pve/qemu-server/*.conf; do
      [[ -f "$conf" ]] || continue
      id="$(basename "$conf" .conf)"
      grep -qiE '^(name|tags):.*immich' "$conf" || continue
      ip="$(qm guest cmd "$id" network-get-interfaces 2>/dev/null | grep -oE '"ip-address" *: *"[0-9.]+"' | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' | grep -v '^127\.' | head -1 || true)"
      [[ -n "$ip" ]] && curl -fs -m 4 "http://${ip}:2283/api/server/ping" >/dev/null 2>&1 && { IMMICH_URL="http://${ip}:2283"; break; }
    done
  fi
  [[ -n "$IMMICH_URL" ]] && ok "Immich gefunden: $IMMICH_URL" || echo "  ${C_DIM}Nicht automatisch gefunden.${C_OFF}"
  IMMICH_URL="$(ask "  Adresse von Immich (leer = später im Browser eintragen)" "$IMMICH_URL")"
  echo
fi

# ---------------------------------------------------------------------------
# Einstellungen
# ---------------------------------------------------------------------------
CTID="${CTID:-$(pvesh get /cluster/nextid)}"
CT_HOSTNAME="${CT_HOSTNAME:-immichhelper}"
TEMPLATE_STORAGE="${TEMPLATE_STORAGE:-local}"
DEBIAN="${DEBIAN:-12}"
DISK_GB="${DISK_GB:-4}"
CORES="${CORES:-2}"
MEMORY_MB="${MEMORY_MB:-1024}"
BRIDGE="${BRIDGE:-vmbr0}"
IP="${IP:-dhcp}"
GW="${GW:-}"
VLAN="${VLAN:-}"
PORT="${PORT:-8080}"

pct status "$CTID" >/dev/null 2>&1 && die "Container $CTID existiert bereits. Wähle eine andere ID mit CTID=…"

if [[ -z "${STORAGE:-}" ]]; then
  for s in local-lvm local-zfs; do
    if pvesm status -content rootdir 2>/dev/null | awk 'NR>1 && $3=="active"{print $1}' | grep -qx "$s"; then STORAGE="$s"; break; fi
  done
  [[ -n "${STORAGE:-}" ]] || STORAGE="$(pvesm status -content rootdir 2>/dev/null | awk 'NR>1 && $3=="active"{print $1; exit}')"
  [[ -n "${STORAGE:-}" ]] || die "Kein Speicher für Container gefunden. Bitte STORAGE=… angeben."
fi

# ---------------------------------------------------------------------------
# Vorlage
# ---------------------------------------------------------------------------
step "Suche die Debian-${DEBIAN}-Vorlage …"
pveam update >/dev/null 2>&1 || warn "Vorlagen-Liste konnte nicht aktualisiert werden – nutze die vorhandene."
TEMPLATE="$(pveam available --section system 2>/dev/null | awk -v d="debian-${DEBIAN}-standard" '$2 ~ d {print $2}' | sort -V | tail -n 1)"
if [[ -z "$TEMPLATE" ]]; then
  TEMPLATE="$(pveam list "$TEMPLATE_STORAGE" 2>/dev/null | awk -v d="debian-${DEBIAN}-standard" '$1 ~ d {sub(/.*\//, "", $1); print $1}' | sort -V | tail -n 1)"
fi
[[ -n "$TEMPLATE" ]] || die "Keine Debian-${DEBIAN}-Vorlage gefunden."
if ! pveam list "$TEMPLATE_STORAGE" 2>/dev/null | grep -q "$TEMPLATE"; then
  step "Lade $TEMPLATE …"
  pveam download "$TEMPLATE_STORAGE" "$TEMPLATE" >/dev/null || die "Download der Vorlage fehlgeschlagen."
fi
ok "Vorlage $TEMPLATE"

# ---------------------------------------------------------------------------
# Container anlegen
# ---------------------------------------------------------------------------
NET="name=eth0,bridge=${BRIDGE},ip=${IP}"
[[ -n "$GW" ]] && NET="${NET},gw=${GW}"
[[ -n "$VLAN" ]] && NET="${NET},tag=${VLAN}"

step "Lege Container ${CTID} (${CT_HOSTNAME}) auf ${STORAGE} an …"
pct create "$CTID" "${TEMPLATE_STORAGE}:vztmpl/${TEMPLATE}" \
  --hostname "$CT_HOSTNAME" --cores "$CORES" --memory "$MEMORY_MB" --swap 512 \
  --rootfs "${STORAGE}:${DISK_GB}" --net0 "$NET" \
  --unprivileged 1 --features nesting=1 --onboot 1 --tags immichhelper \
  --description "ImmichHelper – Fotos in Immich aussortieren und ordnen
https://github.com/${REPO}

Port: ${PORT}
Anmelden mit dem Immich-Konto. Arbeitet nur über die Immich-API, braucht keinen NAS-Zugriff." >/dev/null
ok "Container ${CTID} angelegt"

step "Starte Container …"
pct start "$CTID"
for _ in $(seq 1 30); do
  pct exec "$CTID" -- bash -c 'getent hosts github.com >/dev/null 2>&1' && break
  sleep 2
done
pct exec "$CTID" -- bash -c 'getent hosts github.com >/dev/null 2>&1' || die "Der Container hat kein Internet (DNS/Netzwerk prüfen: pct enter ${CTID})."
ok "Container läuft und ist online"

# ---------------------------------------------------------------------------
step "Installiere ImmichHelper im Container (dauert 1–3 Minuten) …"
pct exec "$CTID" -- bash -c "export DEBIAN_FRONTEND=noninteractive; apt-get update -qq >/dev/null && apt-get install -y -qq curl ca-certificates >/dev/null"
SCRIPT="$(curl -fsSL "${RAW}/install.sh")" || die "install.sh konnte nicht geladen werden (${RAW}/install.sh)."
pct exec "$CTID" -- env IH_REPO="$REPO" IH_BRANCH="$BRANCH" IH_PORT="$PORT" IH_IMMICH_URL="$IMMICH_URL" IH_NTFY_TOPIC="${NTFY_TOPIC:-}" bash -c "$SCRIPT"

CT_IP="$(pct exec "$CTID" -- hostname -I 2>/dev/null | awk '{print $1}')"
echo
echo "  ${C_OK}ImmichHelper ist bereit!${C_OFF}"
echo
echo "    Adresse:   ${C_INFO}http://${CT_IP:-<IP-des-Containers>}:${PORT}${C_OFF}"
echo "    Anmelden:  mit deinem Immich-Konto (E-Mail + Passwort)"
[[ -z "$IMMICH_URL" ]] && echo "    Beim ersten Öffnen fragt ImmichHelper nach der Adresse von Immich."
echo
echo "  ${C_DIM}Von unterwegs/mit Domain: im Nginx Proxy Manager einen Proxy-Host auf ${CT_IP:-<IP>}:${PORT} anlegen."
echo "  Update später: dieses Skript erneut ausführen oder im Container „immichhelper update“.${C_OFF}"
echo
