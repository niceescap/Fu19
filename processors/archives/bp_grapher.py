#!/usr/bin/env python3
# ~/fjc/processors/bp_grapher.py

"""
bp_grapher.py — ByPass Grapher Agent
────────────────────────────────────────────────────────────────────

Pipeline :
    fit_analysis.json
        → LLM (Groq / llama-3.3-70b-versatile)
        → snippet HTML premium
        → rider_metrics_snippet.html

Objectif :
    Bypasser complètement matplotlib/SVG spline
    et laisser le LLM produire directement :
        - HTML
        - SVG
        - CSS
        - direction artistique

Python conserve :
    - l'analyse
    - la structuration
    - les garde-fous
    - la réduction de tokens

────────────────────────────────────────────────────────────────────
"""

import os
import sys
import json
import time
import textwrap
from pathlib import Path

import requests

# ──────────────────────────────────────────────────────────────────────────────
# ROOT
# ──────────────────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ──────────────────────────────────────────────────────────────────────────────
# Config robuste
# ──────────────────────────────────────────────────────────────────────────────

try:
    import core.config as config

    FIT_OUTPUT_FILE = getattr(
        config,
        "FIT_OUTPUT_FILE",
        PROJECT_ROOT / "data" / "fit_analysis.json"
    )

    METRICS_HTML = getattr(
        config,
        "METRICS_HTML",
        PROJECT_ROOT
        / "data"
        / "metrics"
        / "rider_metrics_snippet.html"
    )

    DEBUG = getattr(config, "DEBUG", False)

except Exception:

    FIT_OUTPUT_FILE = (
        PROJECT_ROOT
        / "data"
        / "fit_analysis.json"
    )

    METRICS_HTML = (
        PROJECT_ROOT
        / "data"
        / "metrics"
        / "rider_metrics_snippet.html"
    )

    DEBUG = False

# ──────────────────────────────────────────────────────────────────────────────
# LLM CONFIG
# ──────────────────────────────────────────────────────────────────────────────

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

GROQ_MODEL = "llama-3.3-70b-versatile"

GROQ_ENV_KEY = "GROQ_SNIPPET_ENHANCER_KEY"

MAX_RETRIES = 3

RETRY_DELAY = 3

TIMEOUT = (15, 120)

MAX_COMPLETION_TOKENS = 2200

TEMPERATURE = 0.65

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)

# ──────────────────────────────────────────────────────────────────────────────
# SESSION HTTP
# ──────────────────────────────────────────────────────────────────────────────

SESSION = requests.Session()

SESSION.headers.update({
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": USER_AGENT,
})

# ==============================================================================
# HELPERS
# ==============================================================================

def log(msg: str) -> None:
    if DEBUG:
        print(f"[bp_grapher] {msg}", flush=True)


def get_api_key() -> str:
    return os.environ.get(
        GROQ_ENV_KEY,
        ""
    ).strip()


def load_json(path: Path) -> dict:

    if not path.exists():
        raise FileNotFoundError(
            f"[bp_grapher] JSON introuvable : {path}"
        )

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ==============================================================================
# VISUAL PROFILE BUILDER
# ==============================================================================

def build_visual_profile(data: dict) -> dict:
    """
    Transforme le JSON physiologique brut
    en payload compact et sémantique pour LLM.
    Gère à la fois des valeurs simples (float) ou des dictionnaires détaillés.
    """

    power_curve = data.get("power_curve", {})
    cadence_curve = data.get("cadence_curve", {})
    cardio = data.get("cardio_profile", {})

    ftp_w = data.get("ftp_w")

    peak_wkg = 0.0
    peak_torque = 0.0
    endurance_wkg = 0.0
    cadence_peak = 0.0

    # ──────────────────────────────────────────────────────────────────────────
    # Analyse puissance
    # ──────────────────────────────────────────────────────────────────────────

    for duration, values in power_curve.items():
        if isinstance(values, dict):
            # données détaillées
            peak_wkg = max(peak_wkg, values.get("w_kg", 0))
            peak_torque = max(peak_torque, values.get("torque_nm", 0))
            if duration in ("20min", "30min", "60min"):
                endurance_wkg = max(endurance_wkg, values.get("w_kg", 0))
        else:
            # valeur simple (ex : float) → considérée comme w_kg
            val = float(values)
            peak_wkg = max(peak_wkg, val)
            if duration in ("20min", "30min", "60min"):
                endurance_wkg = max(endurance_wkg, val)

    # ──────────────────────────────────────────────────────────────────────────
    # Analyse cadence
    # ──────────────────────────────────────────────────────────────────────────

    for values in cadence_curve.values():
        if isinstance(values, dict):
            cadence_peak = max(cadence_peak, values.get("rpm_avg", 0))
        else:
            cadence_peak = max(cadence_peak, float(values))

    # ──────────────────────────────────────────────────────────────────────────
    # Profil cardio
    # ──────────────────────────────────────────────────────────────────────────

    cardio_bias = cardio.get("cursor", 0.5)

    # ──────────────────────────────────────────────────────────────────────────
    # Classification
    # ──────────────────────────────────────────────────────────────────────────

    if peak_wkg >= 16:
        rider_type = "explosive sprinter"
    elif endurance_wkg >= 5:
        rider_type = "endurance rider"
    else:
        rider_type = "all-rounder"

    if cardio_bias >= 0.65:
        cardio_type = "anaerobic"
    elif cardio_bias <= 0.35:
        cardio_type = "diesel"
    else:
        cardio_type = "balanced"

    # ──────────────────────────────────────────────────────────────────────────
    # Payload réduit
    # ──────────────────────────────────────────────────────────────────────────

    return {
        "rider_type": rider_type,
        "cardio_type": cardio_type,
        "ftp_w": ftp_w,
        "peak_power_wkg": round(peak_wkg, 1),
        "peak_torque_nm": round(peak_torque, 1),
        "peak_cadence_rpm": round(cadence_peak, 0),
        "cardio_bias": round(cardio_bias, 2),
        "power_curve": power_curve,
        "cadence_curve": cadence_curve,
    }


# ==============================================================================
# PROMPT
# ==============================================================================

def build_prompt(profile: dict) -> str:

    profile_json = json.dumps(
        profile,
        indent=2,
        ensure_ascii=False,
    )

    return textwrap.dedent(f"""
    You are an elite sports telemetry designer.

    Generate a COMPLETE responsive HTML snippet with inline SVG and inline CSS.

    OBJECTIVE:
    Create a premium cyclist physiological dashboard card from structured performance metrics.

    STYLE:
    - modern AMOLED telemetry
    - luxury sports laboratory aesthetic
    - clean typography
    - elegant radial visualization
    - subtle gradients
    - minimal but emotional
    - premium wearable-tech feeling
    - cinematic data visualization

    TECHNICAL CONSTRAINTS:
    - return ONLY raw HTML
    - no markdown
    - no explanations
    - no code fences
    - mobile-first layout
    - max-width: 520px
    - lightweight SVG
    - inline SVG only
    - inline CSS only
    - no JavaScript
    - no external libraries
    - no external fonts
    - optimized and compact output

    VISUAL RULES:
    - explosive profiles should feel aggressive and sharp
    - endurance profiles should feel fluid and smooth
    - torque visualization should feel muscular
    - cadence should feel dynamic and energetic
    - cardio gauge should feel premium and readable
    - preserve clarity and hierarchy
    - avoid clutter

    REQUIRED SECTIONS:
    1. title/header
    2. radial physiological graph
    3. cardio gauge
    4. compact metrics row
    5. elegant labels

    GRAPH REQUIREMENTS:
    - radial/polar inspired visualization
    - layered data rings are allowed
    - visual depth preferred over scientific precision
    - prioritize aesthetics + readability
    - SVG must remain compact

    DATA:
    {profile_json}
    """)


# ==============================================================================
# LLM CALL
# ==============================================================================

def call_llm(prompt: str) -> str:

    api_key = get_api_key()

    if not api_key:
        raise RuntimeError(
            f"{GROQ_ENV_KEY} non définie"
        )

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "temperature": TEMPERATURE,
        "max_tokens": MAX_COMPLETION_TOKENS,
    }

    log(f"Prompt size : {len(prompt)} chars")

    response = SESSION.post(
        GROQ_API_URL,
        headers={
            "Authorization": f"Bearer {api_key}"
        },
        json=payload,
        timeout=TIMEOUT,
    )

    log(f"HTTP status : {response.status_code}")

    if response.status_code != 200:

        raise RuntimeError(
            f"HTTP {response.status_code}\n"
            f"{response.text}"
        )

    body = response.json()

    try:
        result = body["choices"][0]["message"]["content"]

    except Exception as exc:
        raise RuntimeError(
            f"Réponse inattendue : {body}"
        ) from exc

    # ──────────────────────────────────────────────────────────────────────────
    # Nettoyage markdown parasite
    # ──────────────────────────────────────────────────────────────────────────

    result = result.strip()

    if result.startswith("```"):

        result = result.replace(
            "```html",
            ""
        )

        result = result.replace(
            "```",
            ""
        )

        result = result.strip()

    return result


def call_llm_with_retry(prompt: str):

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):

        try:

            log(
                f"Tentative "
                f"{attempt}/{MAX_RETRIES}"
            )

            result = call_llm(prompt)

            log("Succès génération")

            return result, None

        except Exception as exc:

            last_error = str(exc)

            log(last_error)

            if attempt < MAX_RETRIES:

                log(
                    f"Retry dans "
                    f"{RETRY_DELAY}s"
                )

                time.sleep(RETRY_DELAY)

    return None, last_error


# ==============================================================================
# MAIN
# ==============================================================================

def main():

    print("[bp_grapher] Chargement JSON...")

    data = load_json(FIT_OUTPUT_FILE)

    print("[bp_grapher] Construction profil visuel...")

    profile = build_visual_profile(data)

    prompt = build_prompt(profile)

    result, error = call_llm_with_retry(prompt)

    if result is None:

        print(
            f"[bp_grapher] ÉCHEC\n"
            f"{error}",
            file=sys.stderr,
        )

        sys.exit(1)

    METRICS_HTML.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    METRICS_HTML.write_text(
        result,
        encoding="utf-8",
    )

    print(
        "[bp_grapher] ✓ "
        f"Snippet généré → {METRICS_HTML}"
    )


if __name__ == "__main__":
    main()
