#!/usr/bin/env bash
#
# Instalador para cPanel con SSH. Se corre UNA vez, desde ~/monitor:
#
#     bash tools/instalar_cpanel.sh
#
# Primero comprueba el terreno y se detiene si algo falta, en vez de instalar
# a medias y fallar tres pasos despues. No toca un .env existente ni pisa la
# base de datos.
set -u

ROJO=$'\033[31m'; VERDE=$'\033[32m'; AMBAR=$'\033[33m'; NEG=$'\033[0m'
ok(){ printf "  ${VERDE}ok${NEG}   %s\n" "$1"; }
mal(){ printf "  ${ROJO}MAL${NEG}  %s\n" "$1"; FALLAS=$((FALLAS+1)); }
avi(){ printf "  ${AMBAR}ojo${NEG}  %s\n" "$1"; }
FALLAS=0

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# El script deduce la raiz de su propia ubicacion, asi que si alguien lo copia
# fuera de <proyecto>/tools/ apuntaria a otro lado. Sin esta comprobacion, una
# copia en /tmp resolvia RAIZ=/ y se ponia a crear un venv en la raiz del
# sistema. Se verifica que la carpeta sea de verdad el proyecto.
for necesario in main.py requirements.txt tests scraper.py; do
  if [ ! -e "$RAIZ/$necesario" ]; then
    printf "${ROJO}MAL${NEG}  '%s' no parece ser el proyecto: falta %s\n" "$RAIZ" "$necesario"
    echo "     Corre el script desde su lugar:  bash tools/instalar_cpanel.sh"
    exit 1
  fi
done
cd "$RAIZ" || exit 1
echo "Monitor de Suelo — instalacion en ${RAIZ}"
echo
echo "1) Terreno"

# --- Python ---
PY=""
for c in python3.12 python3.11 python3.10 python3.9 python3; do
  command -v "$c" >/dev/null 2>&1 || continue
  v=$("$c" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null) || continue
  if "$c" -c 'import sys;sys.exit(0 if sys.version_info[:2]>=(3,9) else 1)' 2>/dev/null; then
    PY="$c"; ok "Python $v en $(command -v "$c")"; break
  fi
done
if [ -z "$PY" ]; then
  mal "no encontre Python 3.9 o mayor."
  avi "en cPanel a veces esta en Software -> Setup Python App, o como python3.11 en el PATH."
fi

# --- Salida a internet: es la que mas se pasa por alto ---
probar_red(){
  local nombre="$1" url="$2" cod
  cod=$(curl -sS -o /dev/null -m 20 -w '%{http_code}' "$url" 2>/dev/null) || cod="000"
  if [ "$cod" = "000" ]; then
    mal "$nombre no responde (sin salida a internet o bloqueado)"
  else
    ok "$nombre alcanzable (HTTP $cod)"
  fi
}
probar_red "api.apify.com"        "https://api.apify.com/v2/logs"
probar_red "nominatim.openstreetmap.org" "https://nominatim.openstreetmap.org/status.php"

# --- Escritura ---
if touch .prueba_escritura 2>/dev/null; then rm -f .prueba_escritura; ok "se puede escribir en ${RAIZ}"
else mal "no se puede escribir en ${RAIZ}"; fi

if [ "$FALLAS" -gt 0 ]; then
  echo
  printf "${ROJO}Se detuvo: %s comprobacion(es) fallaron.${NEG}\n" "$FALLAS"
  echo "Sin salida a internet el pipeline no puede llamar a Apify, y sin Python"
  echo "3.9+ no arranca. Manda esta salida y vemos el Camino C (pipeline afuera,"
  echo "el hosting solo publica archivos)."
  exit 1
fi

echo
echo "2) Entorno"
if [ -d .venv ]; then ok ".venv ya existe, se reutiliza"
else "$PY" -m venv .venv && ok ".venv creado" || { mal "no pude crear el venv"; exit 1; }
fi
./.venv/bin/pip install --quiet --upgrade pip >/dev/null 2>&1
if ./.venv/bin/pip install --quiet -r requirements.txt; then ok "dependencias instaladas"
else mal "fallo la instalacion de dependencias"; exit 1; fi

mkdir -p logs && ok "carpeta logs/ lista"

echo
echo "3) Configuracion"
if [ -f .env ]; then
  ok ".env ya existe (no se toca)"
  grep -q '^APIFY_TOKEN=apify_api_[A-Za-z0-9]' .env && ok "APIFY_TOKEN con pinta de estar puesto" \
    || avi "revisa que APIFY_TOKEN tenga el token real"
else
  cp .env.example .env
  avi ".env creado desde la plantilla — FALTA poner el APIFY_TOKEN antes de correr"
fi

echo
echo "4) Pruebas (no usan token ni red)"
for t in tests/test_*.py; do
  if ./.venv/bin/python "$t" >/dev/null 2>&1; then ok "$(basename "$t")"
  else mal "$(basename "$t")"; fi
done
[ "$FALLAS" -gt 0 ] && { echo; printf "${ROJO}Hay pruebas fallando; no sigas hasta ver por que.${NEG}\n"; exit 1; }

echo
echo "5) Falta hacer a mano"
cat <<TXT

  a) Pon el token en .env  (Apify -> Settings -> Integrations -> API tokens)

  b) Prueba en seco, sin escribir en la base ni gastar de mas:
       cd ${RAIZ} && ./.venv/bin/python main.py --seco --max 20

  c) Publica la carpeta. Lo que se sirve tiene que SER ~/monitor/web, no una
     copia, para que el cron escriba directo sobre lo publicado:
       ln -s ${RAIZ}/web ~/public_html/monitor
     (o apunta el subdominio monitor.trcimplan.gob.mx a esa ruta)

  d) El cron, una sola linea. Corre cada 3 dias, no a diario: Apify cobra
     \$0.005 por resultado y llegan ~125 por corrida (\$0.60), asi que a
     diario son ~\$18/mes contra \$5 de credito gratuito.
       0 3 */3 * * cd ${RAIZ} && git pull --quiet && ./.venv/bin/python main.py >> logs/corridas.log 2>&1

  e) NO bajes MAX_RESULTADOS_POR_FUENTE para gastar menos. Lo que no llega se
     lee como desaparecido y la corrida reporta bajas falsas. La perilla del
     costo es la frecuencia de esta linea, no el tope.

TXT
printf "${VERDE}Terreno verificado y entorno listo.${NEG}\n"
