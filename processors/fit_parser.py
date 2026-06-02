#!/usr/bin/env python3
"""
fit_parser.py — Agent 1 (v3.1)
Parse un ou plusieurs fichiers .fit et produit :
  1. un fit_analysis.json (résultats calculés, utilisé par le grapher)
  2. une archive mensuelle dans ~/fjc/data/storage/profiles/<athlete_id>/metrics/metrics_YYYY-MM.json
     (un seul fichier par mois, écrasé à chaque parsing du même mois)

Environnement : Python 3 / Termux
Dépendance    : pip install fitparse numpy

Entrée  : dossier FIT_INPUT_DIR (config.py) ou --input-dir
Sortie  : FIT_OUTPUT_FILE (config.py) ou --output
           + archive mensuelle si --athlete-id est fourni
"""

import os
import sys
import json
import math
import argparse
import numpy as np
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

try:
    from fitparse import FitFile
except ImportError:
    sys.exit("❌  Installe fitparse : pip install fitparse")

# ── Rendre la racine du projet importable (quel que soit le répertoire d'exécution) ─
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ── Import config centrale (fallback si exécution directe) ───────────────────
try:
    from core.config import (
        FIT_INPUT_DIR,
        FIT_OUTPUT_FILE,
        FIT_ACQUISITION_MODE,
        FIT_NO_RECORDS,
    )
except ImportError:
    FIT_INPUT_DIR       = Path(".") / "fit_input"
    FIT_OUTPUT_FILE     = Path(".") / "fit_analysis.json"
    FIT_ACQUISITION_MODE = "directory"
    FIT_NO_RECORDS      = False

# ── Constantes ────────────────────────────────────────────────────────────────
FIT_EPOCH = datetime(1989, 12, 31, tzinfo=timezone.utc)
MPS_TO_KMH = 3.6

CURVE_DURATIONS = [
    (5,     "5s"),
    (10,    "10s"),
    (15,    "15s"),
    (30,    "30s"),
    (45,    "45s"),
    (60,    "1min"),
    (120,   "2min"),
    (300,   "5min"),
    (600,   "10min"),
    (900,   "15min"),
    (1800,  "30min"),
    (2700,  "45min"),
    (3600,  "60min"),
]

# Racine du stockage long terme
DATA_STORAGE_ROOT = Path.home() / "fjc" / "data" / "storage" / "profiles"

# ── Helpers ───────────────────────────────────────────────────────────────────
def safe_float(val, scale=1.0):
    try:
        return float(val) * scale
    except (TypeError, ValueError):
        return None

def rolling_max_avg(series: list, window: int) -> float:
    if len(series) < window:
        return 0.0
    best = 0.0
    s = sum(series[:window])
    if s / window > best:
        best = s / window
    for i in range(window, len(series)):
        s += series[i] - series[i - window]
        avg = s / window
        if avg > best:
            best = avg
    return best

# ── Parsing d'un fichier .fit ─────────────────────────────────────────────────
def parse_fit_file(filepath: Path) -> dict:
    fit = FitFile(str(filepath))
    power_series   = []
    cadence_series = []
    fc_series      = []
    speed_series   = []
    has_power      = False
    has_cadence    = False
    has_heart_rate = False
    has_speed      = False

    for msg in fit.get_messages("record"):
        d = {f.name: f.value for f in msg.fields}
        pwr = safe_float(d.get("power"))
        cad = safe_float(d.get("cadence"))
        fc  = safe_float(d.get("heart_rate"))
        spd = safe_float(d.get("speed"), MPS_TO_KMH)

        if pwr is not None and pwr > 0: has_power = True
        if cad is not None and cad > 0: has_cadence = True
        if fc  is not None and fc  > 30: has_heart_rate = True
        if spd is not None and spd > 0: has_speed = True

        power_series.append(pwr if pwr is not None else 0.0)
        cadence_series.append(cad if cad is not None else 0.0)
        fc_series.append(fc if fc is not None else 0.0)
        speed_series.append(spd if spd is not None else 0.0)

    return {
        "power": power_series, "cadence": cadence_series,
        "fc": fc_series, "speed": speed_series,
        "has_power": has_power, "has_cadence": has_cadence,
        "has_heart_rate": has_heart_rate, "has_speed": has_speed,
        "n_points": len(power_series),
    }

# ── Courbes par métrique ─────────────────────────────────────────────────────
def build_metric_curve(series, has_data, weight_kg=None):
    if not has_data or len(series) == 0:
        return None
    curve = {}
    is_power = (weight_kg is not None)
    for secs, label in CURVE_DURATIONS:
        if len(series) < secs: continue
        avg = rolling_max_avg(series, secs)
        if avg < 0.001: continue
        entry = {}
        if is_power:
            entry["watts"] = round(avg, 1)
            entry["w_kg"]  = round(avg / weight_kg, 3)
        else:
            entry["value"] = round(avg, 1)
        curve[label] = entry
    return curve if curve else None

# ── Profil cardio ─────────────────────────────────────────────────────────────
def build_cardio_profile(fc_series):
    fc_valid = [f for f in fc_series if f > 30]
    if len(fc_valid) < 30:
        return None
    fc_array = np.array(fc_valid)
    fc_max = float(np.percentile(fc_array, 99))
    seuil_zone_haute = fc_max * 0.85
    zone_haute_pct   = float(np.mean(fc_array > seuil_zone_haute) * 100)
    diffs = np.diff(fc_array)
    montees = diffs[diffs > 0]
    fc_acceleration = float(np.mean(montees) * 60) if len(montees) > 0 else 0.0
    accel_score = float(np.clip((fc_acceleration - 5) / (40 - 5), 0, 1))
    zone_score  = float(np.clip((zone_haute_pct - 20) / (70 - 20), 0, 1))
    cursor = round(0.6 * accel_score + 0.4 * zone_score, 3)
    return {
        "cursor": cursor,
        "fc_acceleration_bpm_min": round(fc_acceleration, 1),
        "zone_haute_pct": round(zone_haute_pct, 1),
        "fc_max_observed": round(fc_max, 0),
    }

# ── FTP ───────────────────────────────────────────────────────────────────────
def estimate_ftp(power_series):
    p60 = rolling_max_avg(power_series, 3600)
    p20 = rolling_max_avg(power_series, 1200)
    p5  = rolling_max_avg(power_series, 300)
    if p60 > 10: return round(p60 * 0.95, 1)
    if p20 > 10: return round(p20 * 0.75, 1)
    if p5  > 10: return round(p5  * 0.55, 1)
    return None

# ── Fusion multi-sessions ─────────────────────────────────────────────────────
def merge_sessions(sessions, weight_kg):
    all_power, all_cadence, all_fc, all_speed = [], [], [], []
    has_power = has_cadence = has_heart_rate = has_speed = False
    for s in sessions:
        all_power.extend(s["power"])
        all_cadence.extend(s["cadence"])
        all_fc.extend(s["fc"])
        all_speed.extend(s["speed"])
        if s["has_power"]:      has_power = True
        if s["has_cadence"]:    has_cadence = True
        if s["has_heart_rate"]: has_heart_rate = True
        if s["has_speed"]:      has_speed = True

    power_curve      = build_metric_curve(all_power, has_power, weight_kg)
    cadence_curve    = build_metric_curve(all_cadence, has_cadence)
    heart_rate_curve = build_metric_curve(all_fc, has_heart_rate)
    speed_curve      = build_metric_curve(all_speed, has_speed)
    ftp_w            = estimate_ftp(all_power) if has_power else None
    cardio           = build_cardio_profile(all_fc) if has_heart_rate else None

    return {
        "power_curve": power_curve, "cadence_curve": cadence_curve,
        "heart_rate_curve": heart_rate_curve, "speed_curve": speed_curve,
        "ftp_w": ftp_w, "cardio_profile": cardio,
        "meta": {
            "sessions_count": len(sessions),
            "has_power": has_power, "has_cadence": has_cadence,
            "has_heart_rate": has_heart_rate, "has_speed": has_speed,
        },
    }

# ── Sauvegarde d'archive mensuelle ───────────────────────────────────────────
def save_archive(data: dict, athlete_id: str, date_str: str):
    """
    Sauvegarde/écrase une copie dans le dossier d'archive de l'athlète,
    sous le nom metrics_YYYY-MM.json (un seul fichier par mois).
    """
    month_str = date_str[:7]  # "YYYY-MM"
    archive_dir = DATA_STORAGE_ROOT / athlete_id / "metrics"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / f"metrics_{month_str}.json"

    with open(archive_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"📦  Archive mensuelle → {archive_path}")

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Parse .fit → fit_analysis.json + archive mensuelle"
    )
    parser.add_argument("--input-dir", default=str(FIT_INPUT_DIR),
                        help="Dossier contenant les fichiers .fit")
    parser.add_argument("--output", default=str(FIT_OUTPUT_FILE),
                        help="Fichier JSON de sortie")
    parser.add_argument("--weight", type=float, required=True,
                        help="Poids du coureur en kg (obligatoire)")
    parser.add_argument("--athlete-id", required=True,
                        help="Identifiant unique de l'athlète (ex: fjc_ath_...). Obligatoire pour l'archivage.")
    args = parser.parse_args()

    input_dir   = Path(os.path.expanduser(args.input_dir))
    output_path = Path(os.path.expanduser(args.output))
    weight_kg   = args.weight
    athlete_id  = args.athlete_id

    fit_files = sorted(input_dir.glob("*.fit"))
    if not fit_files:
        sys.exit(f"❌  Aucun fichier .fit trouvé dans : {input_dir}")

    print(f"📂  Mode d'acquisition : {FIT_ACQUISITION_MODE}")
    print(f"👤  Athlète            : {athlete_id}")

    sessions = []
    for fp in fit_files:
        print(f"  ↳ parsing {fp.name} …", end=" ", flush=True)
        try:
            sessions.append(parse_fit_file(fp))
            print("✓")
        except Exception as e:
            print(f"⚠️  erreur : {e}")

    if not sessions:
        sys.exit("❌  Aucune session valide parsée.")

    result = merge_sessions(sessions, weight_kg)

    now_utc = datetime.now(timezone.utc)
    output = {
        "generated_at": now_utc.isoformat(),
        "rider_weight_kg": weight_kg,
        "athlete_id": athlete_id,
        "sessions_parsed": len(sessions),
        **result,
    }

    # Écriture du fichier principal (utilisé par le grapher)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # Sauvegarde d'archive mensuelle
    date_str = now_utc.strftime("%Y-%m-%d")
    save_archive(output, athlete_id, date_str)

    # Résumé console
    print(f"\n✅  fit_analysis.json écrit → {output_path}")
    print(f"   Sessions          : {result['meta']['sessions_count']}")
    print(f"   Puissancemètre    : {'✓' if result['meta']['has_power'] else '✗'}")
    print(f"   Capteur cadence   : {'✓' if result['meta']['has_cadence'] else '✗'}")
    print(f"   Cardiofréquencemètre : {'✓' if result['meta']['has_heart_rate'] else '✗'}")
    print(f"   Vitesse (GPS)     : {'✓' if result['meta']['has_speed'] else '✗'}")
    if result["ftp_w"]:
        print(f"   FTP estimé        : {result['ftp_w']} W")
    if result["cardio_profile"]:
        c = result["cardio_profile"]
        print(f"   Profil cardio     : curseur {c['cursor']} "
              f"({'Full Gaz' if c['cursor'] > 0.6 else 'Diesel' if c['cursor'] < 0.4 else 'Mixte'})")
    for name, curve in [("Puissance", result["power_curve"]),
                         ("Cadence",   result["cadence_curve"]),
                         ("FC",        result["heart_rate_curve"]),
                         ("Vitesse",   result["speed_curve"])]:
        if curve:
            print(f"   Courbe {name:9s} : {', '.join(curve.keys())}")

if __name__ == "__main__":
    main()
