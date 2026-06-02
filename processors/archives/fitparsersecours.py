#!/usr/bin/env python3
"""
fit_parser.py — Agent 1 (v3)
Parse un ou plusieurs fichiers .fit et produit un fit_analysis.json léger,
contenant les meilleures moyennes par intervalle pour chaque grandeur disponible
(puissance, cadence, fréquence cardiaque, vitesse), le profil cardio et le FTP.

Environnement : Python 3 / Termux
Dépendance    : pip install fitparse numpy

Entrée  : dossier FIT_INPUT_DIR (config.py) ou --input-dir
Sortie  : FIT_OUTPUT_FILE (config.py) ou --output
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

# Durées de calcul des meilleures moyennes (secondes → label)
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

# ── Poids coureur ─────────────────────────────────────────────────────────────
# TODO : cette valeur sera injectée dynamiquement par fiche_builder.py
#        via un fichier JSON coureur (ex. profiles/lazare.json → "weight_kg")
#        ou via l'argument CLI --weight.
#        En attendant, on applique 30 kg pour les tests sur le profil de Lazare.
RIDER_WEIGHT_KG_DEFAULT = 30.0


# ── Helpers ───────────────────────────────────────────────────────────────────

def safe_float(val, scale=1.0):
    try:
        return float(val) * scale
    except (TypeError, ValueError):
        return None


def rolling_max_avg(series: list, window: int) -> float:
    """Meilleure moyenne glissante sur `window` points consécutifs."""
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
    """
    Lit un fichier .fit et retourne les séries temporelles brutes
    (usage interne uniquement — ne sort pas dans le JSON final).
    """
    fit = FitFile(str(filepath))

    power_series   = []   # W, 1 point/s
    cadence_series = []   # RPM
    fc_series      = []   # BPM
    speed_series   = []   # km/h
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

        if pwr is not None and pwr > 0:
            has_power = True
        if cad is not None and cad > 0:
            has_cadence = True
        if fc is not None and fc > 30:
            has_heart_rate = True
        if spd is not None and spd > 0:
            has_speed = True

        power_series.append(pwr   if pwr  is not None else 0.0)
        cadence_series.append(cad if cad  is not None else 0.0)
        fc_series.append(fc       if fc   is not None else 0.0)
        speed_series.append(spd   if spd  is not None else 0.0)

    return {
        "power":       power_series,
        "cadence":     cadence_series,
        "fc":          fc_series,
        "speed":       speed_series,
        "has_power":   has_power,
        "has_cadence": has_cadence,
        "has_heart_rate": has_heart_rate,
        "has_speed":   has_speed,
        "n_points":    len(power_series),
    }


# ── Calcul des courbes par métrique ──────────────────────────────────────────

def build_metric_curve(
    series: list,
    has_data: bool,
    weight_kg: Optional[float] = None,
) -> Optional[dict]:
    """
    Calcule la meilleure moyenne sur chaque durée de CURVE_DURATIONS.
    - Pour la puissance : ajoute 'watts' et 'w_kg' si weight_kg fourni.
    - Pour les autres métriques : renvoie simplement la valeur moyenne.
    Retourne None si pas de données (has_data == False).
    """
    if not has_data or len(series) == 0:
        return None

    curve = {}
    is_power = (weight_kg is not None)

    for secs, label in CURVE_DURATIONS:
        if len(series) < secs:
            continue
        avg = rolling_max_avg(series, secs)
        if avg < 0.001:  # pas de valeur significative
            continue

        entry = {}
        if is_power:
            entry["watts"] = round(avg, 1)
            entry["w_kg"]  = round(avg / weight_kg, 3)
        else:
            # cadence, FC, vitesse : une seule valeur
            entry["value"] = round(avg, 1)

        curve[label] = entry

    return curve if curve else None


# ── Profil cardio ─────────────────────────────────────────────────────────────

def build_cardio_profile(fc_series: list) -> Optional[dict]:
    """
    Produit un curseur Diesel ↔ Full Gaz depuis la série FC.
    (inchangé par rapport à la v2)
    """
    fc_valid = [f for f in fc_series if f > 30]
    if len(fc_valid) < 30:
        return None

    fc_array = np.array(fc_valid)
    fc_max = float(np.percentile(fc_array, 99))
    seuil_zone_haute = fc_max * 0.85
    zone_haute_pct   = float(np.mean(fc_array > seuil_zone_haute) * 100)

    diffs = np.diff(fc_array)
    montees = diffs[diffs > 0]
    if len(montees) > 0:
        fc_acceleration = float(np.mean(montees) * 60)
    else:
        fc_acceleration = 0.0

    accel_score = float(np.clip((fc_acceleration - 5) / (40 - 5), 0, 1))
    zone_score = float(np.clip((zone_haute_pct - 20) / (70 - 20), 0, 1))
    cursor = round(0.6 * accel_score + 0.4 * zone_score, 3)

    return {
        "cursor":                  cursor,
        "fc_acceleration_bpm_min": round(fc_acceleration, 1),
        "zone_haute_pct":          round(zone_haute_pct, 1),
        "fc_max_observed":         round(fc_max, 0),
    }


# ── FTP ───────────────────────────────────────────────────────────────────────

def estimate_ftp(power_series: list) -> Optional[float]:
    """
    Estimation FTP depuis la série de puissance consolidée.
    Priorité : 95 % P60 → 75 % P20 → heuristique 55 % P5.
    """
    p60 = rolling_max_avg(power_series, 3600)
    p20 = rolling_max_avg(power_series, 1200)
    p5  = rolling_max_avg(power_series, 300)

    if p60 > 10:
        return round(p60 * 0.95, 1)
    if p20 > 10:
        return round(p20 * 0.75, 1)
    if p5 > 10:
        return round(p5  * 0.55, 1)
    return None


# ── Fusion multi-sessions ─────────────────────────────────────────────────────

def merge_sessions(sessions: list, weight_kg: float) -> dict:
    """
    Agrège toutes les sessions en une seule série par métrique,
    puis calcule les courbes (puissance, cadence, FC, vitesse), le FTP
    et le profil cardio.
    """
    all_power   = []
    all_cadence = []
    all_fc      = []
    all_speed   = []
    has_power   = False
    has_cadence = False
    has_heart_rate = False
    has_speed   = False
    sessions_count = len(sessions)

    for s in sessions:
        all_power.extend(s["power"])
        all_cadence.extend(s["cadence"])
        all_fc.extend(s["fc"])
        all_speed.extend(s["speed"])
        if s["has_power"]:
            has_power = True
        if s["has_cadence"]:
            has_cadence = True
        if s["has_heart_rate"]:
            has_heart_rate = True
        if s["has_speed"]:
            has_speed = True

    # Courbes par métrique
    power_curve = build_metric_curve(all_power, has_power, weight_kg)
    cadence_curve = build_metric_curve(all_cadence, has_cadence)
    heart_rate_curve = build_metric_curve(all_fc, has_heart_rate)
    speed_curve = build_metric_curve(all_speed, has_speed)

    # FTP
    ftp_w = estimate_ftp(all_power) if has_power else None

    # Profil cardio
    cardio = build_cardio_profile(all_fc) if has_heart_rate else None

    return {
        "power_curve":       power_curve,
        "cadence_curve":     cadence_curve,
        "heart_rate_curve":  heart_rate_curve,
        "speed_curve":       speed_curve,
        "ftp_w":             ftp_w,
        "cardio_profile":    cardio,
        "meta": {
            "sessions_count":  sessions_count,
            "has_power":       has_power,
            "has_cadence":     has_cadence,
            "has_heart_rate":  has_heart_rate,
            "has_speed":       has_speed,
        },
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse .fit → fit_analysis.json (courbes de puissance, cadence, FC, vitesse)"
    )
    parser.add_argument(
        "--input-dir", default=str(FIT_INPUT_DIR),
        help="Dossier contenant les fichiers .fit",
    )
    parser.add_argument(
        "--output", default=str(FIT_OUTPUT_FILE),
        help="Fichier JSON de sortie",
    )
    parser.add_argument(
        "--weight", type=float, default=RIDER_WEIGHT_KG_DEFAULT,
        help="Poids du coureur en kg (défaut : 30 kg pour tests Lazare)",
    )
    args = parser.parse_args()

    input_dir  = Path(os.path.expanduser(args.input_dir))
    output_path = Path(os.path.expanduser(args.output))
    weight_kg   = args.weight

    # ── Collecte des fichiers .fit ──
    fit_files = sorted(input_dir.glob("*.fit"))
    if not fit_files:
        sys.exit(f"❌  Aucun fichier .fit trouvé dans : {input_dir}")

    print(f"📂  Mode d'acquisition : {FIT_ACQUISITION_MODE}")

    # ── Parsing (données brutes en mémoire uniquement) ──
    sessions = []
    for fp in fit_files:
        print(f"  ↳ parsing {fp.name} …", end=" ", flush=True)
        try:
            session = parse_fit_file(fp)
            sessions.append(session)
            print("✓")
        except Exception as e:
            print(f"⚠️  erreur : {e}")

    if not sessions:
        sys.exit("❌  Aucune session valide parsée.")

    # ── Fusion & calculs ──
    result = merge_sessions(sessions, weight_kg)

    # ── Construction du JSON final (léger) ──
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rider_weight_kg": weight_kg,
        **result,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # ── Résumé console ──
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
            durations = list(curve.keys())
            print(f"   Courbe {name:9s} : {', '.join(durations)}")


if __name__ == "__main__":
    main()
