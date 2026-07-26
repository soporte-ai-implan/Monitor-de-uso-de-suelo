"""
scheduler.py — corre el pipeline en automático cada N horas.

Es la opción "todo en un proceso": útil si el monitor va a vivir en un servidor
donde puedes dejar un servicio corriendo. Si prefieres el programador del
sistema operativo (Task Scheduler en Windows, cron en Linux), ve
docs/scheduler.md — para IMPLAN es la opción recomendada porque sobrevive
reinicios sin configurar un servicio aparte.

Uso:
    python scheduler.py                 corre cada INTERVALO_HORAS (default 24)
    python scheduler.py --horas 12      cada 12 horas
    python scheduler.py --ahora         corre una vez de inmediato y se queda
"""
from __future__ import annotations

import argparse
import logging
import os
import pathlib
import signal
import sys
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from dotenv import load_dotenv

import main as pipeline

load_dotenv()

LOGS = pathlib.Path(__file__).resolve().parent / "logs"
LOGS.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOGS / "scheduler.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("monitor")


def tarea() -> None:
    log.info("--- disparando corrida programada ---")
    try:
        r = pipeline.correr_monitor()
        log.info(
            "corrida '%s': nuevos=%s actualizados=%s bajas=%s",
            r.get("estatus"), r.get("nuevos"), r.get("actualizados"), r.get("dados_de_baja"),
        )
        if r.get("aviso"):
            log.warning(r["aviso"])
    except Exception:
        # No se re-lanza: si truena una corrida, el scheduler debe seguir vivo
        # para intentar la siguiente. El error queda en la tabla `corridas`.
        log.exception("la corrida falló; el scheduler sigue activo")


def main() -> int:
    ap = argparse.ArgumentParser(description="Scheduler del Monitor de Suelo")
    ap.add_argument("--horas", type=float, default=float(os.getenv("INTERVALO_HORAS", "24")))
    ap.add_argument("--ahora", action="store_true", help="correr una vez al arrancar")
    args = ap.parse_args()

    sched = BlockingScheduler(timezone="America/Monterrey")
    sched.add_job(
        tarea,
        trigger=IntervalTrigger(hours=args.horas),
        id="corrida_monitor",
        name="Corrida del Monitor de Suelo",
        max_instances=1,       # nunca dos corridas encimadas
        coalesce=True,         # si se atrasó, una sola corrida al despertar
        misfire_grace_time=3600,
        next_run_time=datetime.now() if args.ahora else None,
    )

    def apagar(signum, frame):  # noqa: ARG001
        log.info("señal recibida, apagando scheduler...")
        sched.shutdown(wait=False)

    signal.signal(signal.SIGINT, apagar)
    signal.signal(signal.SIGTERM, apagar)

    log.info("scheduler arriba: cada %s horas (zona America/Monterrey)", args.horas)
    log.info("Ctrl+C para detener")
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        pass
    log.info("scheduler detenido")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
