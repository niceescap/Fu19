#!/usr/bin/env python3
# ~/fjc/processors/graph_transformer.py

"""
Agent 3 — Graph Transformer

Pipeline :
    rider_metrics_snippet.html
        → [Groq Llama-4-Scout]
        → rider_metrics_enhanced.html

Contrat d'interface :
  - Entrée  : RIDER_METRICS_HTML
  - Sortie  : RIDER_METRICS_ENHANCED_HTML
  - Prompt  : ENHANCE_PROMPT_FILE
  - Modèle  : GROQ_MODEL via API Groq
  - Retry   : GROQ_MAX_RETRIES fois puis fallback
"""

import os
import sys
import time
import json
from pathlib import Path

import requests
from requests.exceptions import RequestException, Timeout

# ──────────────────────────────────────────────────────────────────────────────
# Import config
# ──────────────────────────────────────────────────────────────────────────────

try:
    from core.config import (
        RIDER_METRICS_HTML,
        RIDER_METRICS_ENHANCED_HTML,
        ENHANCE_PROMPT_FILE,
        GROQ_MODEL,
        GROQ_MAX_RETRIES,
        DEBUG,
    )
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    from core.config import (
        RIDER_METRICS_HTML,
        RIDER_METRICS_ENHANCED_HTML,
        ENHANCE_PROMPT_FILE,
        GROQ_MODEL,
        GROQ_MAX_RETRIES,
        DEBUG,
    )

# ──────────────────────────────────────────────────────────────────────────────
# Constantes
# ──────────────────────────────────────────────────────────────────────────────

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

GROQ_ENV_KEY = "GROQ_SNIPPET_ENHANCER_KEY"

RETRY_DELAY_S = 3

MAX_TOKENS = 8192

REQUEST_TIMEOUT = (15, 60)

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)

# ──────────────────────────────────────────────────────────────────────────────
# Session HTTP persistante
# ──────────────────────────────────────────────────────────────────────────────

SESSION = requests.Session()

SESSION.headers.update({
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Accept-Encoding": "identity",
    "Connection": "keep-alive",
    "User-Agent": USER_AGENT,
})

# ==============================================================================
# Helpers
# ==============================================================================

def _log(msg: str) -> None:
    """Affiche uniquement en mode DEBUG."""
    if DEBUG:
        print(f"[graph_transformer] {msg}", flush=True)


def _get_api_key() -> str:
    """
    Lit la clé API dynamiquement depuis l'environnement.
    .strip() évite les \n parasites issus de ~/.bashrc
    """
    return os.environ.get(GROQ_ENV_KEY, "").strip()


def _load_text(path: Path, label: str) -> str:
    """Charge un fichier texte UTF-8."""
    if not path.exists():
        raise FileNotFoundError(
            f"[graph_transformer] Fichier introuvable : {label} → {path}"
        )

    return path.read_text(encoding="utf-8")


def _build_prompt(prompt_template: str, svg_content: str) -> str:
    """Injecte le SVG dans le placeholder {SVG_CONTENT}."""
    if "{SVG_CONTENT}" not in prompt_template:
        raise ValueError(
            "[graph_transformer] "
            "Le prompt ne contient pas le placeholder {SVG_CONTENT}"
        )

    return prompt_template.replace("{SVG_CONTENT}", svg_content)


# ==============================================================================
# API GROQ
# ==============================================================================

def _call_groq(prompt: str) -> str:
    """
    Appelle l'API Groq et retourne le texte généré.
    """

    api_key = _get_api_key()

    if not api_key:
        raise ValueError(
            f"[graph_transformer] Variable {GROQ_ENV_KEY} vide."
        )

    headers = {
        "Authorization": f"Bearer {api_key}",
    }

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "max_tokens": MAX_TOKENS,
        "temperature": 0.3,
    }

    payload_json = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    if DEBUG:
        _log(f"Modèle : {GROQ_MODEL}")
        _log(f"Longueur prompt : {len(prompt)} caractères")
        _log(f"Clé détectée : {api_key[:12]}…")
        _log(f"Taille payload JSON : {len(payload_json)} bytes")

    try:
        response = SESSION.post(
            GROQ_API_URL,
            headers=headers,
            data=payload_json.encode("utf-8"),
            timeout=REQUEST_TIMEOUT,
        )

    except Timeout as exc:
        raise TimeoutError(
            "[graph_transformer] Timeout API Groq"
        ) from exc

    except RequestException as exc:
        raise ConnectionError(
            f"[graph_transformer] Erreur réseau : {exc}"
        ) from exc

    # ──────────────────────────────────────────────────────────────────────────
    # DEBUG HTTP
    # ──────────────────────────────────────────────────────────────────────────

    if DEBUG:
        _log(f"HTTP status : {response.status_code}")

    if response.status_code != 200:

        response_text = response.text.strip()

        error_msg = (
            f"[graph_transformer] "
            f"HTTP {response.status_code} — "
            f"{response.reason}\n"
            f"Réponse serveur :\n"
            f"{response_text}"
        )

        raise RuntimeError(error_msg)

    # ──────────────────────────────────────────────────────────────────────────
    # Parsing JSON
    # ──────────────────────────────────────────────────────────────────────────

    try:
        body = response.json()

    except json.JSONDecodeError as exc:
        raise ValueError(
            "[graph_transformer] Réponse JSON invalide."
        ) from exc

    try:
        return body["choices"][0]["message"]["content"]

    except (KeyError, IndexError) as exc:
        raise ValueError(
            "[graph_transformer] "
            f"Structure Groq inattendue : {body}"
        ) from exc


def _call_groq_with_retry(prompt: str) -> tuple[str | None, str | None]:
    """
    Retry intelligent de l'appel API.
    """

    last_error = None

    for attempt in range(1, GROQ_MAX_RETRIES + 1):

        try:
            _log(f"Tentative {attempt}/{GROQ_MAX_RETRIES}")

            result = _call_groq(prompt)

            _log(f"Succès tentative {attempt}")

            return result, None

        except Exception as exc:  # noqa: BLE001

            last_error = str(exc)

            _log(last_error)

            if attempt < GROQ_MAX_RETRIES:
                _log(
                    f"Nouvelle tentative dans "
                    f"{RETRY_DELAY_S}s..."
                )

                time.sleep(RETRY_DELAY_S)

    return None, last_error


# ==============================================================================
# Fonction principale
# ==============================================================================

def transform(
    input_path: Path = RIDER_METRICS_HTML,
    output_path: Path = RIDER_METRICS_ENHANCED_HTML,
    prompt_path: Path = ENHANCE_PROMPT_FILE,
) -> dict:
    """
    Pipeline principal.

    Retour :
        {
            "success": bool,
            "output_path": str,
            "ENHANCED_GRAPH": str,
            "error": str | None,
            "fallback": bool,
        }
    """

    # ──────────────────────────────────────────────────────────────────────────
    # 1. Chargement fichiers
    # ──────────────────────────────────────────────────────────────────────────

    try:
        svg_content = _load_text(
            input_path,
            "snippet SVG d'entrée",
        )

        prompt_template = _load_text(
            prompt_path,
            "prompt de transformation",
        )

    except FileNotFoundError as exc:

        error_msg = str(exc)

        print(error_msg, file=sys.stderr)

        return {
            "success": False,
            "output_path": str(output_path),
            "ENHANCED_GRAPH": "",
            "error": error_msg,
            "fallback": False,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # 2. Construction prompt
    # ──────────────────────────────────────────────────────────────────────────

    try:
        full_prompt = _build_prompt(
            prompt_template,
            svg_content,
        )

    except ValueError as exc:

        error_msg = str(exc)

        print(error_msg, file=sys.stderr)

        return {
            "success": False,
            "output_path": str(output_path),
            "ENHANCED_GRAPH": svg_content,
            "error": error_msg,
            "fallback": True,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # 3. Vérification clé API
    # ──────────────────────────────────────────────────────────────────────────

    api_key = _get_api_key()

    if not api_key:

        error_msg = (
            f"[graph_transformer] "
            f"{GROQ_ENV_KEY} non définie."
        )

        print(error_msg, file=sys.stderr)

        enhanced = svg_content

        fallback = True

    else:

        enhanced, error_msg = _call_groq_with_retry(full_prompt)

        fallback = enhanced is None

        if fallback:

            print(
                f"[graph_transformer] "
                f"ÉCHEC après "
                f"{GROQ_MAX_RETRIES} tentatives.\n"
                f"Erreur : {error_msg}\n"
                f"→ fallback snippet original.",
                file=sys.stderr,
            )

            enhanced = svg_content

    # ──────────────────────────────────────────────────────────────────────────
    # 4. Écriture sortie
    # ──────────────────────────────────────────────────────────────────────────

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        enhanced,
        encoding="utf-8",
    )

    _log(f"Fichier écrit : {output_path}")

    # ──────────────────────────────────────────────────────────────────────────
    # 5. Retour pipeline
    # ──────────────────────────────────────────────────────────────────────────

    return {
        "success": not fallback,
        "output_path": str(output_path),
        "ENHANCED_GRAPH": enhanced,
        "error": error_msg if fallback else None,
        "fallback": fallback,
    }


# ==============================================================================
# CLI
# ==============================================================================

if __name__ == "__main__":

    api_key = _get_api_key()

    if api_key:
        _log(f"Clé API détectée : {api_key[:12]}…")
        _log(f"Longueur clé : {len(api_key)}")
    else:
        _log("Aucune clé API détectée")

    result = transform()

    if result["success"]:

        print(
            "[graph_transformer] "
            f"✓ Transformation réussie "
            f"→ {result['output_path']}"
        )

    else:

        status = (
            "FALLBACK (snippet original)"
            if result["fallback"]
            else "ERREUR"
        )

        print(
            f"[graph_transformer] "
            f"{status} "
            f"→ {result['output_path']}"
        )

        if result["error"]:
            print(
                f"  Détail : {result['error']}",
                file=sys.stderr,
            )

    sys.exit(0 if result["success"] else 1)
