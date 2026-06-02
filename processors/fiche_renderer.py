# ~/fjc/processors/fiche_renderer.py
"""
FICHE RENDERER — Transformateur BDD → HTML
PIPELINE COMPLET FJC :
    [BDD Athlete]
         │
         ▼
    athlete_to_dict()
         │  Transforme l'objet SQLAlchemy en dict Python propre
         │  Normalise les valeurs manquantes
         │  Résout la photo/avatar selon photo_status :
         │      AVATAR_PENDING → avatar gris statique (/static/avatar_default.png)
         │      AVATAR         → PNG colorisé du coffre-fort (/static/profiles/<id>/images/avatar.png)
         │      (legacy)       → ancienne logique photo_raw.jpg ignorée
         │  Détermine les flags (avatar_ready, metrics_certified...)
         ▼
    [dict athlete]
         │
         ├──► build_meta_pills()
         │        Lit : uci_id_data, donnees_performance
         │        Produit : HTML des pills (profil, poids uniquement)
         │
         ├──► build_infos_col()
         │        Lit : uci_id_data, donnees_performance, palmares
         │        Décide : disposition de la colonne droite selon le contenu
         │          → Pas de palmarès : Club (large) + Profil + Fédération
         │          → Palmarès court (1-3) : Club + Poids + Palmarès compact
         │          → Palmarès long (4+) : Club (small) + Palmarès scrollable (grow)
         │        Produit : HTML injecté dans {{ infos_col_html }}
         │
         ▼
    [3 blocs HTML]
         │
         ├──► app.py → render_template("fiche_athlete.html", ...)  [temps réel]
         └──► fiche_builder.py → render_prototype(...)              [batch]
"""

import sys
from pathlib import Path
from data.models import Athlete
import re
from urllib.parse import urlparse, parse_qs

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# ==============================================================================
# CONSTANTES AVATAR
# ==============================================================================

AVATAR_DEFAULT_URL = "/static/avatar_default.png"
PROFILES_STATIC_PREFIX = "/static/profiles"

# ==============================================================================
# 1. SÉRIALISATION BDD → DICT
# ==============================================================================

def athlete_to_dict(ath: Athlete) -> dict:
    """
    Transforme un objet SQLAlchemy Athlete en dict exploitable par les templates.
    Normalise les valeurs absentes pour éviter les KeyError dans les templates.

    LOGIQUE AVATAR (remplace l'ancienne logique photo) :
        photo_status == "AVATAR_PENDING"
            → avatar_url  = AVATAR_DEFAULT_URL  (gris statique)
            → avatar_ready = False
        photo_status == "AVATAR"
            → avatar_url  = /static/profiles/<id>/images/avatar.png
            → avatar_ready = True
        Tout autre statut (legacy "PENDING", "VALIDATED", None)
            → avatar_url  = AVATAR_DEFAULT_URL  (gris statique, cas dégradé)
            → avatar_ready = False
    """
    from core.config import PROFILES_DIR

    uci    = ath.uci_id_data          or {}
    perf   = ath.donnees_performance  or {}
    medias = ath.medias               or {}

    has_fit_data = bool(perf.get("derniers_fichiers_fit"))

    # ── Résolution avatar ──────────────────────────────────────────────
    photo_status = ath.photo_status or "AVATAR_PENDING"
    if photo_status == "AVATAR":
        avatar_path = PROFILES_DIR / ath.id / "images" / "avatar.png"
        if avatar_path.exists():
            avatar_url   = f"{PROFILES_STATIC_PREFIX}/{ath.id}/images/avatar.png"
            avatar_ready = True
        else:
            avatar_url   = AVATAR_DEFAULT_URL
            avatar_ready = False
    else:
        avatar_url   = AVATAR_DEFAULT_URL
        avatar_ready = False

    # ── Métriques image (hélice artichaut) ─────────────────────────────
    metrics_png_path = perf.get("metrics_png_path")
    if metrics_png_path:
        png_file = Path(metrics_png_path)
        if png_file.exists():
            metrics_url = f"{PROFILES_STATIC_PREFIX}/{ath.id}/metrics/rider_metrics.png"
        else:
            metrics_url = None
    else:
        metrics_url = None

    return {
        # Identité
        "id":             ath.id,
        "nom":            ath.nom,
        "prenom":         ath.prenom,
        "date_naissance": ath.date_naissance,
        "sexe":           ath.sexe,
        "nationalite":    (ath.nationalite or "FR").upper(),
        "junior_horizon": ath.junior_horizon,
        "status":         ath.status,

        # Avatar
        "avatar_url":    avatar_url,
        "avatar_ready":  avatar_ready,
        "photo_status":  photo_status,

        # Métriques
        "metrics_certified": has_fit_data,
        "svg_helix":         perf.get("svg_helix"),        # conservé pour compatibilité
        "metrics_url":       metrics_url,                  # nouveau champ pour l'image PNG

        # Blocs JSON bruts
        "uci_id_data":         uci,
        "donnees_performance": perf,
        "palmares":            ath.palmares  or [],
        "medias":              medias,
        "partenaires":         ath.partenaires or [],
    }

# ==============================================================================
# 2. SLOT — META PILLS (sans doublons UCI / Fédération / Certified)
# ==============================================================================

def build_meta_pills(athlete: dict) -> str:
    uci  = athlete.get("uci_id_data", {})
    perf = athlete.get("donnees_performance", {})
    pills = []

    # On ne met plus l'UCI ni la fédération ici (affichés ailleurs)
    # if uci.get("number"):
    #     pills.append(f'<span class="pill">UCI — {uci["number"]}</span>')
    # if uci.get("federation"):
    #     pills.append(f'<span class="pill">{uci["federation"]}</span>')

    if perf.get("profil_manuel"):
        pills.append(f'<span class="pill">🚴 {perf["profil_manuel"]}</span>')

    if perf.get("poids"):
        pills.append(f'<span class="pill">{perf["poids"]} kg</span>')

    # Badge Certified déjà sous l'avatar → retiré
    # if athlete.get("metrics_certified"):
    #     pills.append('<span class="pill certified">✅ Certified Datas</span>')

    return "\n".join(pills)

# ==============================================================================
# 3. SLOT — COLONNE INFOS DROITE
# ==============================================================================

def build_infos_col(athlete: dict) -> str:
    uci    = athlete.get("uci_id_data", {})
    perf   = athlete.get("donnees_performance", {})
    palm   = athlete.get("palmares", [])
    blocks = []
    nb_palm = len(palm)

    club = uci.get("club", "")
    if club:
        size = "large" if nb_palm == 0 else ("small" if nb_palm > 3 else "")
        blocks.append(_info_card("Club", club, size))

    if nb_palm == 0:
        if perf.get("profil_manuel"):
            blocks.append(_info_card("Profil", perf["profil_manuel"]))
        fed = uci.get("federation", "")
        if fed:
            blocks.append(_info_card("Fédération", fed))
    elif nb_palm <= 3:
        if perf.get("poids"):
            blocks.append(_info_card("Poids", f'{perf["poids"]} kg'))
        blocks.append(_palmares_card(palm, grow=False))
    else:
        blocks.append(_palmares_card(palm, grow=True))

    return "\n".join(blocks)

def _info_card(label: str, value: str, size: str = "") -> str:
    size_class = f"info-value {size}".strip()
    return f'''<div class="info-card">
    <div class="info-label">{label}</div>
    <div class="{size_class}">{value}</div>
</div>'''

def _palmares_card(palm: list, grow: bool = False) -> str:
    grow_class = "info-card grow" if grow else "info-card"
    items_html = ""
    for r in palm:
        cert = '<span class="p-cert">✓ certifié</span>' if r.get("certified") else ""
        cat  = f'<span class="p-date">{r.get("categorie", "")}</span>' if r.get("categorie") else ""
        items_html += f'''<div class="palmares-item">
        <div class="p-rank">{r.get("classement", "")}</div>
        <div class="p-detail">
            <div class="p-race">{r.get("course", "")}</div>
            <div class="p-date">{r.get("date", "")}</div>
            {cat}
        </div>
        {cert}
    </div>'''

    return f'''<div class="{grow_class}">
    <div class="info-label">Palmarès</div>
    <div class="palmares-list">{items_html}</div>
</div>'''

# ==============================================================================
# 4. SLOT — FOOTER MÉDIAS
# ==============================================================================

MEDIA_ICONS = {
    "instagram": "📸",
    "strava":    "🚴",
    "youtube":   "▶️",
    "tiktok":    "🎵",
    "presse":    "📰",
    "sponsor":   "🤝",
    "autre":     "🔗",
}

# ==============================================================================
# 5. POINT D'ENTRÉE — construit les 3 slots d'un coup
# ==============================================================================

def render_athlete_slots(ath: Athlete) -> tuple[dict, str, str, str]:
    athlete = athlete_to_dict(ath)
    return (
        athlete,
        build_meta_pills(athlete),
        build_infos_col(athlete),
    )
