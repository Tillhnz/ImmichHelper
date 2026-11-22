#!/usr/bin/env bash
# ===========================================================================
#  ImmichHelper – Installation IM Container (Debian/Ubuntu)
#
#  Normalerweise nicht direkt aufrufen, sondern auf dem Proxmox-Host:
#    bash -c "$(curl -fsSL https://raw.githubusercontent.com/Tillhnz/ImmichHelper/main/proxmox/create-lxc.sh)"
#
#  Im Container:
#    bash install.sh              installieren
#    immichhelper update          aktualisieren   (= bash /opt/immichhelper/install.sh --update)
#    immichhelper uninstall       entfernen       (deine Fotos in Immich bleiben unberührt)
# ===========================================================================
set -euo pipefail

REPO="${IH_REPO:-Tillhnz/ImmichHelper}"
BRANCH="${IH_BRANCH:-main}"
INSTALL_DIR="/opt/immichhelper"
STATE_DIR="/var/lib/immichhelper"
ENV_FILE="/etc/immichhelper.env"
SERVICE="immichhelper"

C_OK=$'\e[1;32m'; C_ERR=$'\e[1;31m'; C_INFO=$'\e[1;36m'; C_DIM=$'\e[2m'; C_OFF=$'\e[0m'
step() { echo "${C_INFO}›${C_OFF} $*"; }
ok()   { echo "${C_OK}✔${C_OFF} $*"; }
die()  { echo "${C_ERR}✘ $*${C_OFF}" >&2; exit 1; }

MODE="install"
case "${1:-}" in
  --update)    MODE="update" ;;
  --uninstall) MODE="uninstall" ;;
  ""|--install) ;;
  *) die "Unbekannte Option: $1 (erlaubt: --update, --uninstall)" ;;
esac
[[ $EUID -eq 0 ]] || die "Bitte als root ausführen."

# Läuft das Skript aus dem Installationsordner, wird es gleich überschrieben → Kopie ausführen
if [[ "${BASH_SOURCE[0]:-}" == "$INSTALL_DIR/install.sh" && -z "${IH_REEXEC:-}" ]]; then
  TMP="$(mktemp /tmp/ih-install.XXXXXX.sh)"
  cp "$INSTALL_DIR/install.sh" "$TMP"
  IH_REEXEC=1 exec bash "$TMP" "$@"
fi

if [[ -f "$ENV_FILE" ]]; then
  _r="$(grep -E '^IH_REPO=' "$ENV_FILE" | cut -d= -f2- || true)"; [[ -n "$_r" && -z "${IH_REPO:-}" ]] && REPO="$_r"
  _b="$(grep -E '^IH_BRANCH=' "$ENV_FILE" | cut -d= -f2- || true)"; [[ -n "$_b" && -z "${IH_BRANCH:-}" ]] && BRANCH="$_b"
fi

# ---------------------------------------------------------------------------
if [[ $MODE == "uninstall" ]]; then
  step "Entferne ImmichHelper …"
  systemctl disable --now "$SERVICE" 2>/dev/null || true
  rm -f "/etc/systemd/system/${SERVICE}.service" /usr/local/bin/immichhelper
  systemctl daemon-reload
  rm -rf "$INSTALL_DIR" "$STATE_DIR" "$ENV_FILE"
  ok "Entfernt. Deine Fotos in Immich wurden nicht angefasst."
  exit 0
fi

echo
echo "  ${C_INFO}ImmichHelper${C_OFF} ${C_DIM}– Fotos in Immich aussortieren und ordnen${C_OFF}"
echo

# ---------------------------------------------------------------------------
step "Benötigte Pakete installieren …"
export DEBIAN_FRONTEND=noninteractive
NEED=()
for p in git python3 python3-venv curl ca-certificates; do dpkg -s "$p" >/dev/null 2>&1 || NEED+=("$p"); done
if ((${#NEED[@]})); then
  apt-get update -qq || true
  apt-get install -y -qq --no-install-recommends "${NEED[@]}" >/dev/null || die "Pakete konnten nicht installiert werden."
fi
ok "Pakete vorhanden"

# ---------------------------------------------------------------------------
step "Programm von GitHub laden (${REPO}, Zweig ${BRANCH}) …"
if [[ -d "$INSTALL_DIR/.git" ]]; then
  git -C "$INSTALL_DIR" remote set-url origin "https://github.com/${REPO}.git"
  git -C "$INSTALL_DIR" fetch -q --depth 1 origin "$BRANCH"
  git -C "$INSTALL_DIR" reset -q --hard FETCH_HEAD
else
  rm -rf "$INSTALL_DIR"
  git clone -q --depth 1 --branch "$BRANCH" "https://github.com/${REPO}.git" "$INSTALL_DIR" \
    || die "Konnte https://github.com/${REPO} nicht laden. Ist das Repository öffentlich und hat der Container Internet?"
fi
ok "Version $(cat "$INSTALL_DIR/VERSION" 2>/dev/null || echo '?')"

# ---------------------------------------------------------------------------
step "Python-Umgebung einrichten …"
SYS_PY="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
VENV_PY="$("$INSTALL_DIR/.venv/bin/python" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)"
if [[ "$VENV_PY" != "$SYS_PY" ]]; then
  rm -rf "$INSTALL_DIR/.venv"
  python3 -m venv "$INSTALL_DIR/.venv"
fi
"$INSTALL_DIR/.venv/bin/pip" install -q --upgrade pip >/dev/null
if ! "$INSTALL_DIR/.venv/bin/pip" install -q -r "$INSTALL_DIR/backend/requirements.txt"; then
  # pillow-heif gibt es nicht für jede Plattform – ohne geht es auch
  grep -v pillow-heif "$INSTALL_DIR/backend/requirements.txt" > /tmp/ih-req.txt
  "$INSTALL_DIR/.venv/bin/pip" install -q -r /tmp/ih-req.txt || die "Python-Pakete konnten nicht installiert werden."
fi
ok "Python-Umgebung bereit"

# ---------------------------------------------------------------------------
if [[ ! -f "$ENV_FILE" ]]; then
  step "Konfiguration anlegen …"
  cat > "$ENV_FILE" <<EOF
# ImmichHelper – Einstellungen. Nach Änderungen: immichhelper restart

# Adresse und Port der Oberfläche
IH_BIND=0.0.0.0
IH_PORT=${IH_PORT:-8080}

# Adresse von Immich im Heimnetz (lässt sich auch in der Oberfläche einstellen), z. B. http://192.168.1.20:2283
IH_IMMICH_URL=${IH_IMMICH_URL:-}
# Eigenes Zertifikat bei https? Dann 1 = Zertifikat nicht prüfen
IH_IMMICH_INSECURE=0

# Wie viele Fotos gleichzeitig geprüft werden (mehr = schneller, aber mehr Last für Immich)
IH_ANALYZE_WORKERS=4

# IP-Adressen eines Reverse-Proxys (z. B. Nginx Proxy Manager), kommagetrennt
IH_TRUSTED_PROXIES=127.0.0.1

# Repository für Updates
IH_REPO=${REPO}
IH_BRANCH=${BRANCH}

# Push-Nachricht bei neuen Versionen (App „ntfy“), leer = aus. Auch in der Oberfläche einstellbar.
IH_NTFY_TOPIC=${IH_NTFY_TOPIC:-}
#IH_NTFY_URL=https://ntfy.sh
#IH_NTFY_TOKEN=
EOF
  chmod 600 "$ENV_FILE"
  ok "Konfiguration: $ENV_FILE"
else
  grep -q '^IH_REPO=' "$ENV_FILE" && sed -i "s#^IH_REPO=.*#IH_REPO=${REPO}#" "$ENV_FILE" || echo "IH_REPO=${REPO}" >> "$ENV_FILE"
fi
mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR"

# ---------------------------------------------------------------------------
step "Dienst einrichten …"
cat > "/etc/systemd/system/${SERVICE}.service" <<EOF
[Unit]
Description=ImmichHelper – Fotos in Immich aussortieren und ordnen
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=${ENV_FILE}
Environment=IH_STATE_DIR=${STATE_DIR}
WorkingDirectory=${INSTALL_DIR}
ExecStart=/usr/bin/env bash -c 'exec ${INSTALL_DIR}/.venv/bin/uvicorn backend.app:app --host "\${IH_BIND:-0.0.0.0}" --port "\${IH_PORT:-8080}" --proxy-headers --forwarded-allow-ips "\${IH_TRUSTED_PROXIES:-127.0.0.1}" --no-server-header --log-level warning --timeout-keep-alive 30'
Restart=on-failure
RestartSec=3
Nice=5

[Install]
WantedBy=multi-user.target
EOF

cat > /usr/local/bin/immichhelper <<EOF
#!/usr/bin/env bash
# ImmichHelper – Hilfsbefehle im Container
set -e
cd ${INSTALL_DIR}
set -a; source ${ENV_FILE}; set +a
export IH_STATE_DIR=${STATE_DIR}
case "\${1:-}" in
  status)     ${INSTALL_DIR}/.venv/bin/python -m backend.cli status ;;
  url)        shift; ${INSTALL_DIR}/.venv/bin/python -m backend.cli url "\$@"; systemctl restart ${SERVICE} ;;
  logout-all) ${INSTALL_DIR}/.venv/bin/python -m backend.cli logout-all ;;
  update)     bash ${INSTALL_DIR}/install.sh --update ;;
  uninstall)  bash ${INSTALL_DIR}/install.sh --uninstall ;;
  logs)       journalctl -u ${SERVICE} -n 100 -f ;;
  restart)    systemctl restart ${SERVICE} ;;
  *) echo "ImmichHelper \$(cat ${INSTALL_DIR}/VERSION)"
     echo "  immichhelper status         Verbindung zu Immich und eingelesene Bibliotheken"
     echo "  immichhelper url <adresse>  Immich-Adresse ändern, z. B. http://192.168.1.20:2283"
     echo "  immichhelper logout-all     Alle Anmeldungen beenden"
     echo "  immichhelper update         Neueste Version installieren"
     echo "  immichhelper logs           Protokoll ansehen"
     echo "  immichhelper restart        Neu starten"
     echo "  immichhelper uninstall      Entfernen (Fotos in Immich bleiben)";;
esac
EOF
chmod +x /usr/local/bin/immichhelper "$INSTALL_DIR/install.sh"

systemctl daemon-reload
systemctl enable -q "$SERVICE"
systemctl restart "$SERVICE"

# shellcheck disable=SC1090
source "$ENV_FILE"
for _ in $(seq 1 20); do
  curl -fs "http://127.0.0.1:${IH_PORT:-8080}/api/health" >/dev/null 2>&1 && break
  sleep 1
done
if ! systemctl is-active -q "$SERVICE"; then
  journalctl -u "$SERVICE" -n 30 --no-pager || true
  die "Der Dienst ist nicht gestartet (siehe Meldungen oben)."
fi
ok "Dienst läuft"

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
ok "Fertig! Öffne im Browser:  ${C_INFO}http://${IP:-<IP-des-Containers>}:${IH_PORT:-8080}${C_OFF}"
echo "  ${C_DIM}Anmelden mit deinem Immich-Konto (E-Mail + Passwort).${C_OFF}"
echo
