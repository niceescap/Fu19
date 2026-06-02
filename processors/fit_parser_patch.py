#!/usr/bin/env python3
"""
fit_parser_patch.py — Adaptateur pour pipeline par profil.
"""
from pathlib import Path
import sys
import json
from datetime import datetime, timezone
from typing import Union, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from processors.fit_parser import parse_fit_file, merge_sessions


def run_for_athlete(
    fit_path: Union[Path, List[Path]],
    weight_kg: float,
    output_dir: Path
) -> Path:
    """
    Parse un ou plusieurs fichiers .fit et produit fit_analysis.json
    dans le dossier du profil. Si plusieurs fichiers sont fournis,
    les sessions sont fusionnées et les métriques moyennées.

    Args:
        fit_path   : chemin unique (Path) ou liste de chemins (List[Path])
        weight_kg  : poids du coureur (issu de la fiche)
        output_dir : dossier du profil (ex: storage/profiles/fjc_ath_xxx)

    Returns:
        Path vers fit_analysis.json généré.
    """
    if not weight_kg or float(weight_kg) <= 0:
        raise ValueError("Poids athlète manquant ou invalide.")

    weight_kg = float(weight_kg)
    output_json = output_dir / "fit_analysis.json"

    # Normalisation : accepte un Path unique ou une liste de Path
    if isinstance(fit_path, (list, tuple)):
        paths = [Path(p) for p in fit_path]
    else:
        paths = [Path(fit_path)]

    if not paths:
        raise ValueError("Aucun fichier .fit fourni.")

    # Parsing de chaque fichier
    sessions = []
    errors = []
    for p in paths:
        try:
            session = parse_fit_file(p)
            sessions.append(session)
        except Exception as e:
            errors.append(f"{p.name} : {e}")

    if not sessions:
        raise RuntimeError(f"Aucune session valide parsée. Erreurs : {errors}")

    # Fusion & calculs (moyenne sur toutes les sessions)
    result = merge_sessions(sessions, weight_kg)

    output = {
        "generated_at":    datetime.now(timezone.utc).isoformat(),
        "rider_weight_kg": weight_kg,
        "athlete_id":      output_dir.name,
        "sessions_parsed": len(sessions),
        **result,
    }

    output_json.parent.mkdir(parents=True, exist_ok=True)
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    return output_json
