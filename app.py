# ~/fjc/app.py
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, send_file, session, jsonify
)
import os
import random as _random
from core.config import (
    SECRET_KEY, TEMPLATES_DIR, STATIC_DIR,
    ALLOWED_PHOTO_EXTENSIONS, ALLOWED_FIT_EXTENSIONS,
    PROFILES_DIR, DEBUG, ADMIN_EMAILS
)
from data.database import SessionLocal
from data.models import Athlete
from processors.fiche_factory import FicheFactory
from processors.fiche_renderer import render_athlete_slots, athlete_to_dict
from data.avatar.avatar_chatbot import avatar_bp

# ── Pipeline FIT ──────────────────────────────────────────────────────────────
from processors.fit_parser_patch import run_for_athlete
from processors.grapher import generate_artichoke, load_analysis
import shutil

# ── JSON ORM ──────────────────────────────────────────────────────────────────
from sqlalchemy.orm.attributes import flag_modified

# ── Auth & Legal ──────────────────────────────────────────────────────────────
from auth.magic_linker import MagicLinker
from core.legal_filters import validate_legal_requirements
from processors.emailer import send_magic_link
from processors.notifier import send_claim_magic_link, send_report_notification
from data.models import athlete_owners
from data.queries import get_user_dashboard_data

# ==============================================================================
app = Flask(
    __name__,
    template_folder=str(TEMPLATES_DIR),
    static_folder=str(STATIC_DIR)
)
app.secret_key = SECRET_KEY
app.register_blueprint(avatar_bp)

from data.medialinks.medialinks_chatbot import medialinks_bp
app.register_blueprint(medialinks_bp, url_prefix="/medialinks")


# ==============================================================================
# UTILITAIRES
# ==============================================================================

def allowed_file(filename: str, allowed: set) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed


def build_stats(athletes: list) -> dict:
    """Calcule les stats macro pour la sidebar de fiches_list."""
    nations = sorted(set(a["nationalite"] for a in athletes if a["nationalite"]))
    years   = sorted(set(a["junior_horizon"] for a in athletes if a["junior_horizon"]))
    return {
        "total":        len(athletes),
        "nb_M":         sum(1 for a in athletes if a["sexe"] == "M"),
        "nb_F":         sum(1 for a in athletes if a["sexe"] == "F"),
        "nb_nations":   len(nations),
        "nb_certified": sum(1 for a in athletes if a["avatar_ready"]),
        "nations":      nations,
        "years":        years,
    }
# ==============================================================================
# UTILITAIRE — Score de complétude (à ajouter dans la section UTILITAIRES)
# Après la fonction build_stats()
# ==============================================================================

def compute_score(athlete: dict) -> int:
    """
    Calcule le score de complétude d'une fiche.
    Utilisé pour le tri et les collections /fiches/completes.
        avatar personnalisé  → +1
        fichiers FIT         → +1 par fichier
        lignes palmarès      → +1 par ligne
        liens médias         → +1 par lien
    """
    score = 0
    if athlete.get("avatar_ready"):
        score += 1
    score += len(athlete.get("donnees_performance", {}).get("derniers_fichiers_fit", []))
    score += len(athlete.get("palmares", []))
    score += len(athlete.get("medias", {}).get("links", {}))
    return score

def get_athlete_or_404(db, athlete_id: str):
    """Récupère un athlète ou flash + redirect si introuvable."""
    ath = db.query(Athlete).filter(Athlete.id == athlete_id).first()
    if not ath:
        flash("❌ Fiche introuvable.", "error")
    return ath


# ==============================================================================
# ROUTE — SERVEUR FICHIERS PROFILS
# ==============================================================================

@app.route("/static/profiles/<athlete_id>/images/<filename>")
def serve_profile_image(athlete_id, filename):
    path = PROFILES_DIR / athlete_id / "images" / filename
    if path.exists():
        return send_file(str(path), mimetype="image/png")
    return "Image non trouvée", 404


@app.route("/static/profiles/<athlete_id>/metrics/<filename>")
def serve_profile_metrics(athlete_id, filename):
    path = PROFILES_DIR / athlete_id / "metrics" / filename
    if path.exists():
        return send_file(str(path), mimetype="image/png")
    return "Image non trouvée", 404

#--commit du nouveau fiche liste----
@app.route("/asset/<filename>")
def serve_asset(filename):
    from werkzeug.utils import secure_filename

    allowed_names  = {"asset_a", "asset_b", "asset_c"}
    allowed_exts   = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".webm"}
    mime_map = {
        ".jpg":  "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png":  "image/png",
        ".webp": "image/webp",
        ".gif":  "image/gif",
        ".mp4":  "video/mp4",
        ".webm": "video/webm",
    }

    safe = secure_filename(filename)
    stem, ext = os.path.splitext(safe)

    if stem not in allowed_names or ext.lower() not in allowed_exts:
        return "Fichier non autorisé", 403

    asset_path = BASE_DIR / "data" / safe
    if not asset_path.exists():
        return "Fichier introuvable", 404

    return send_file(str(asset_path), mimetype=mime_map.get(ext.lower(), "application/octet-stream"))


# ==============================================================================
# ROUTES — NAVIGATION
# ==============================================================================

@app.route("/")
def index():
    return redirect(url_for("fiches_list"))

# ==============================================================================
# ROUTE — /fiches REFACTORISÉE (remplace l'existante)
# Filtres serveur + tri serveur + pagination 30 + highlights
# ==============================================================================

@app.route("/fiches")
def fiches_list():
    """
    Page principale — grille universelle avec :
    - Ligne 1 fixe : carte contrôle + créer + 3 assets
    - Ligne 2 : 5 highlights dorés (stub tailer)
    - Ligne 3+ : 30 fiches paginées, filtrées et triées côté serveur
    """
    db = SessionLocal()
    try:
        # ── Paramètres GET ────────────────────────────────────────────────────
        page     = request.args.get("page", 1, type=int)
        q        = request.args.get("q", "").strip()
        per_page = 30  # 30 fiches dès la ligne 3

        # ── Requête de base ───────────────────────────────────────────────────
        query = db.query(Athlete).filter(Athlete.status == "PUBLIC")

        # Recherche texte sur nom + prénom (insensible à la casse)
        if q:
            query = query.filter(
                (Athlete.nom.ilike(f"%{q}%")) |
                (Athlete.prenom.ilike(f"%{q}%"))
            )

        # ── Chargement + tri alphabétique serveur ─────────────────────────────
        # On charge tout pour trier (SQLite ne supporte pas ORDER BY sur JSON)
        # Sur PostgreSQL en prod, on pourra passer à .order_by() natif
        athletes_raw = query.all()
        athletes_all = [athlete_to_dict(a) for a in athletes_raw]
        athletes_all = sort_athletes_server(athletes_all, sort_key="alpha")

        total       = len(athletes_all)
        total_pages = (total + per_page - 1) // per_page
        start       = (page - 1) * per_page
        athletes    = athletes_all[start:start + per_page]

        # ── Stats globales (toujours sur 100% de la base) ─────────────────────
        # On recalcule sur athletes_all pour avoir les bons totaux
        # même quand une recherche est active
        all_for_stats = [athlete_to_dict(a) for a in
                         db.query(Athlete).filter(Athlete.status == "PUBLIC").all()]
        stats = build_stats(all_for_stats)

        # ── Highlights — 5 fiches actives (stub tailer) ───────────────────────
        highlight_ids      = get_highlight_ids(db, n=5)
        highlights_raw     = [
            db.query(Athlete).filter(Athlete.id == aid).first()
            for aid in highlight_ids
        ]
        highlights = [athlete_to_dict(a) for a in highlights_raw if a]

        # ── Assets détectés automatiquement ───────────────────────────────────
        asset_a = detect_asset("asset_a")
        asset_b = detect_asset("asset_b")
        asset_c = detect_asset("asset_c")

        # ── Ownership ─────────────────────────────────────────────────────────
        user_email       = session.get("user_email")
        user_athlete_ids = _get_user_athlete_ids(db, user_email, athletes)

    finally:
        db.close()

    return render_template("fiches_list.html",
                           athletes=athletes,
                           highlights=highlights,
                           stats=stats,
                           user_athlete_ids=user_athlete_ids,
                           current_user_email=user_email,
                           page=page,
                           total_pages=total_pages,
                           total=total,
                           q=q,
                           asset_a=asset_a,
                           asset_b=asset_b,
                           asset_c=asset_c)



# ==============================================================================
# ROUTES — COLLECTIONS PARTAGEABLES
# À ajouter après fiches_list()
# ==============================
        
# ==============================================================================
# ROUTES — COLLECTIONS REFACTORISÉES
# Toutes avec tri alphabétique serveur sauf /completes
# ==============================================================================

@app.route("/fiches/nation/<code>")
def fiches_nation(code):
    """
    Collection par nation.
    URL : /fiches/nation/fr, /fiches/nation/be, /fiches/nation/nl ...
    Le code est normalisé en majuscules pour correspondre à la BDD.
    """
    code_upper = code.upper()
    page       = request.args.get("page", 1, type=int)
    per_page   = 30

    db = SessionLocal()
    try:
        athletes_raw = db.query(Athlete).filter(
            Athlete.status      == "PUBLIC",
            Athlete.nationalite == code_upper
        ).all()

        athletes_all = sort_athletes_server(
            [athlete_to_dict(a) for a in athletes_raw],
            sort_key="alpha"
        )

        total       = len(athletes_all)
        total_pages = (total + per_page - 1) // per_page
        start       = (page - 1) * per_page
        athletes    = athletes_all[start:start + per_page]

        user_email       = session.get("user_email")
        user_athlete_ids = _get_user_athlete_ids(db, user_email, athletes)

        asset_a = detect_asset("asset_a")
        asset_b = detect_asset("asset_b")
        asset_c = detect_asset("asset_c")
        stats   = build_stats([athlete_to_dict(a) for a in
                               db.query(Athlete).filter(Athlete.status == "PUBLIC").all()])
    finally:
        db.close()

    nation_names = {
        "FR": "France", "BE": "Belgique", "NL": "Pays-Bas",
        "GB": "Grande-Bretagne", "DE": "Allemagne", "ES": "Espagne",
        "IT": "Italie", "PT": "Portugal", "CH": "Suisse",
        "DK": "Danemark", "SE": "Suède", "NO": "Norvège",
        "PL": "Pologne", "CZ": "République Tchèque", "SK": "Slovaquie",
        "AT": "Autriche", "HU": "Hongrie", "RO": "Roumanie",
        "HR": "Croatie", "SI": "Slovénie", "LU": "Luxembourg",
        "IE": "Irlande", "AU": "Australie", "NZ": "Nouvelle-Zélande",
        "US": "États-Unis", "CA": "Canada", "JP": "Japon",
        "HK": "Hong Kong", "CN": "Chine", "ZA": "Afrique du Sud",
    }
    nation_label = nation_names.get(code_upper, code_upper)

    return render_template("fiches_collection.html",
                           athletes=athletes,
                           user_athlete_ids=user_athlete_ids,
                           current_user_email=user_email,
                           stats=stats,
                           asset_a=asset_a, asset_b=asset_b, asset_c=asset_c,
                           page=page, total_pages=total_pages, total=total,
                           collection_id="nation",
                           collection_code=code_upper,
                           titre=f"Coureurs {nation_label}",
                           description=f"Découvrez les {total} jeunes talents {nation_label} référencés sur fU19.",
                           emoji="🌍",
                           url_base=f"/fiches/nation/{code}")


@app.route("/fiches/filles")
def fiches_filles():
    """Collection cyclistes féminines — tri alphabétique."""
    page     = request.args.get("page", 1, type=int)
    per_page = 30

    db = SessionLocal()
    try:
        athletes_raw = db.query(Athlete).filter(
            Athlete.status == "PUBLIC",
            Athlete.sexe   == "F"
        ).all()

        athletes_all = sort_athletes_server(
            [athlete_to_dict(a) for a in athletes_raw],
            sort_key="alpha"
        )

        total       = len(athletes_all)
        total_pages = (total + per_page - 1) // per_page
        athletes    = athletes_all[(page-1)*per_page : page*per_page]

        user_email       = session.get("user_email")
        user_athlete_ids = _get_user_athlete_ids(db, user_email, athletes)
        asset_a = detect_asset("asset_a")
        asset_b = detect_asset("asset_b")
        asset_c = detect_asset("asset_c")
        stats   = build_stats([athlete_to_dict(a) for a in
                               db.query(Athlete).filter(Athlete.status == "PUBLIC").all()])
    finally:
        db.close()

    return render_template("fiches_collection.html",
                           athletes=athletes,
                           user_athlete_ids=user_athlete_ids,
                           current_user_email=user_email,
                           stats=stats,
                           asset_a=asset_a, asset_b=asset_b, asset_c=asset_c,
                           page=page, total_pages=total_pages, total=total,
                           collection_id="filles",
                           titre="Cyclistes Féminines U19",
                           description=f"Découvrez les {total} jeunes cyclistes féminines référencées sur fU19.",
                           emoji="🚴‍♀️",
                           url_base="/fiches/filles")


@app.route("/fiches/garcons")
def fiches_garcons():
    """Collection cyclistes masculins — tri alphabétique."""
    page     = request.args.get("page", 1, type=int)
    per_page = 30

    db = SessionLocal()
    try:
        athletes_raw = db.query(Athlete).filter(
            Athlete.status == "PUBLIC",
            Athlete.sexe   == "M"
        ).all()

        athletes_all = sort_athletes_server(
            [athlete_to_dict(a) for a in athletes_raw],
            sort_key="alpha"
        )

        total       = len(athletes_all)
        total_pages = (total + per_page - 1) // per_page
        athletes    = athletes_all[(page-1)*per_page : page*per_page]

        user_email       = session.get("user_email")
        user_athlete_ids = _get_user_athlete_ids(db, user_email, athletes)
        asset_a = detect_asset("asset_a")
        asset_b = detect_asset("asset_b")
        asset_c = detect_asset("asset_c")
        stats   = build_stats([athlete_to_dict(a) for a in
                               db.query(Athlete).filter(Athlete.status == "PUBLIC").all()])
    finally:
        db.close()

    return render_template("fiches_collection.html",
                           athletes=athletes,
                           user_athlete_ids=user_athlete_ids,
                           current_user_email=user_email,
                           stats=stats,
                           asset_a=asset_a, asset_b=asset_b, asset_c=asset_c,
                           page=page, total_pages=total_pages, total=total,
                           collection_id="garcons",
                           titre="Cyclistes Masculins U19",
                           description=f"Découvrez les {total} jeunes cyclistes masculins référencés sur fU19.",
                           emoji="🚵",
                           url_base="/fiches/garcons")


@app.route("/fiches/junior/<int:year>")
def fiches_junior(year):
    """
    Collection par génération (année horizon junior).
    URL : /fiches/junior/2027, /fiches/junior/2028 ...
    junior_horizon = année_naissance + 17
    """
    page     = request.args.get("page", 1, type=int)
    per_page = 30

    db = SessionLocal()
    try:
        athletes_raw = db.query(Athlete).filter(
            Athlete.status         == "PUBLIC",
            Athlete.junior_horizon == year
        ).all()

        athletes_all = sort_athletes_server(
            [athlete_to_dict(a) for a in athletes_raw],
            sort_key="alpha"
        )

        total       = len(athletes_all)
        total_pages = (total + per_page - 1) // per_page
        athletes    = athletes_all[(page-1)*per_page : page*per_page]

        user_email       = session.get("user_email")
        user_athlete_ids = _get_user_athlete_ids(db, user_email, athletes)
        asset_a = detect_asset("asset_a")
        asset_b = detect_asset("asset_b")
        asset_c = detect_asset("asset_c")
        stats   = build_stats([athlete_to_dict(a) for a in
                               db.query(Athlete).filter(Athlete.status == "PUBLIC").all()])
    finally:
        db.close()

    return render_template("fiches_collection.html",
                           athletes=athletes,
                           user_athlete_ids=user_athlete_ids,
                           current_user_email=user_email,
                           stats=stats,
                           asset_a=asset_a, asset_b=asset_b, asset_c=asset_c,
                           page=page, total_pages=total_pages, total=total,
                           collection_id="junior",
                           collection_year=year,
                           titre=f"Génération Junior {year}",
                           description=f"Découvrez les {total} coureurs juniors de la génération {year} sur fU19.",
                           emoji="📅",
                           url_base=f"/fiches/junior/{year}")


@app.route("/fiches/completes")
def fiches_completes():
    """
    Collection des profils les plus complets.
    Seule collection avec tri par score décroissant (pas alphabétique).
    """
    page     = request.args.get("page", 1, type=int)
    per_page = 30

    db = SessionLocal()
    try:
        athletes_raw = db.query(Athlete).filter(Athlete.status == "PUBLIC").all()
        athletes_all = sort_athletes_server(
            [athlete_to_dict(a) for a in athletes_raw],
            sort_key="score"  # Exception : score décroissant
        )

        total       = len(athletes_all)
        total_pages = (total + per_page - 1) // per_page
        athletes    = athletes_all[(page-1)*per_page : page*per_page]

        user_email       = session.get("user_email")
        user_athlete_ids = _get_user_athlete_ids(db, user_email, athletes)
        asset_a = detect_asset("asset_a")
        asset_b = detect_asset("asset_b")
        asset_c = detect_asset("asset_c")
        stats   = build_stats([athlete_to_dict(a) for a in athletes_raw])
    finally:
        db.close()

    return render_template("fiches_collection.html",
                           athletes=athletes,
                           user_athlete_ids=user_athlete_ids,
                           current_user_email=user_email,
                           stats=stats,
                           asset_a=asset_a, asset_b=asset_b, asset_c=asset_c,
                           page=page, total_pages=total_pages, total=total,
                           collection_id="completes",
                           titre="Profils les plus complets",
                           description=f"Les {total} fiches les mieux documentées sur fU19.",
                           emoji="⭐",
                           url_base="/fiches/completes")


@app.route("/fiches/decouverte")
def fiches_decouverte():
    """
    Sélection aléatoire — renouvelée à chaque visite.
    Pas de pagination (60 max, aléatoire).
    """
    db = SessionLocal()
    try:
        athletes_raw = db.query(Athlete).filter(Athlete.status == "PUBLIC").all()
        athletes_all = [athlete_to_dict(a) for a in athletes_raw]
        athletes     = _random.sample(athletes_all, min(60, len(athletes_all)))

        user_email       = session.get("user_email")
        user_athlete_ids = _get_user_athlete_ids(db, user_email, athletes)
        asset_a = detect_asset("asset_a")
        asset_b = detect_asset("asset_b")
        asset_c = detect_asset("asset_c")
        stats   = build_stats([athlete_to_dict(a) for a in athletes_raw])
    finally:
        db.close()

    return render_template("fiches_collection.html",
                           athletes=athletes,
                           user_athlete_ids=user_athlete_ids,
                           current_user_email=user_email,
                           stats=stats,
                           asset_a=asset_a, asset_b=asset_b, asset_c=asset_c,
                           page=1, total_pages=1, total=len(athletes),
                           collection_id="decouverte",
                           titre="Découverte du jour",
                           description=f"Découvrez {len(athletes)} jeunes coureurs sélectionnés aléatoirement sur fU19.",
                           emoji="🌍",
                           url_base="/fiches/decouverte")
# ==============================================================================
# UTILITAIRE INTERNE — ownership pour les collections
# ==============================================================================

def _get_user_athlete_ids(db, user_email: str, athletes: list) -> list:
    """Retourne la liste des athlete_id que l'utilisateur connecté possède."""
    if not user_email:
        return []
    user_email_clean = user_email.strip().lower()
    if user_email_clean in ADMIN_EMAILS:
        return [a["id"] for a in athletes]
    user_data = get_user_dashboard_data(db, user_email_clean)
    if user_data and user_data.athletes:
        return [a.id for a in user_data.athletes]
    return []

def detect_asset(name: str) -> dict | None:
    """
    Cherche un fichier asset_a / asset_b / asset_c dans /data/asset/.
    ...
    """
    asset_dir = BASE_DIR / "data" 

    image_exts = [".jpg", ".jpeg", ".png", ".webp", ".gif"]
    video_exts = [".mp4", ".webm"]

    for ext in image_exts + video_exts:
        candidate = asset_dir / f"{name}{ext}"
        if candidate.exists():
            asset_type = "video" if ext in video_exts else "image"
            return {
                "path": f"/asset/{name}{ext}",
                "type": asset_type,
                "ext":  ext
            }
    return None


# ------------------------------------------------------------------------------
# UTILITAIRE — Calcul du tri serveur
# À ajouter après detect_asset()
# ------------------------------------------------------------------------------

def sort_athletes_server(athletes: list, sort_key: str = "alpha") -> list:
    """
    Trie une liste de dicts athlètes côté serveur.

    sort_key :
        "alpha"  → alphabétique sur nom puis prénom (défaut universel)
        "score"  → score de complétude décroissant (collection /completes uniquement)
        "age"    → date de naissance décroissante (plus jeune en premier)
    """
    if sort_key == "score":
        return sorted(athletes, key=lambda a: compute_score(a), reverse=True)

    if sort_key == "age":
        # dob format YYYY-MM-DD — tri décroissant = plus jeune en premier
        return sorted(
            athletes,
            key=lambda a: a.get("date_naissance", "0000-00-00"),
            reverse=True
        )

    # Défaut : alphabétique sur nom puis prénom
    return sorted(
        athletes,
        key=lambda a: (a.get("nom", ""), a.get("prenom", ""))
    )


# ------------------------------------------------------------------------------
# UTILITAIRE — Highlights (stub — sera remplacé par tailer daemon)
# À ajouter après sort_athletes_server()
# ------------------------------------------------------------------------------

def get_highlight_ids(db, n: int = 5) -> list:
    """
    Retourne les n athlete_id des fiches les plus récemment actives.

    STUB ACTUEL : retourne les n fiches avec avatar + au moins 1 média,
    triées aléatoirement. Ce stub sera remplacé par la lecture des logs
    tailer quand le daemon /surveillance sera opérationnel.

    La signature de cette fonction restera identique après le remplacement,
    ce qui permet de ne pas modifier le reste du code.
    """
    athletes_raw = db.query(Athlete).filter(
        Athlete.status      == "PUBLIC",
        Athlete.photo_status == "AVATAR"
    ).all()

    # Filtre : au moins 1 lien média (fiche "active")
    candidates = [
        a for a in athletes_raw
        if a.medias and a.medias.get("links")
    ]

    if not candidates:
        # Fallback : n'importe quelles fiches avec avatar
        candidates = athletes_raw

    # Sélection aléatoire parmi les candidats (stub — tailer donnera un vrai ordre)
    sample = _random.sample(candidates, min(n, len(candidates)))
    return [a.id for a in sample]



#--fin modif commit fiche_list----------

@app.route("/fiche/<athlete_id>")
def fiche_athlete(athlete_id):
    """Fiche publique d'un coureur."""
    db = SessionLocal()
    try:
        ath = get_athlete_or_404(db, athlete_id)
        if not ath:
            return redirect(url_for("fiches_list"))
        athlete = athlete_to_dict(ath)

        # Tri des médias par position (persistée par le chatbot agenceur)
        links = athlete.get("medias", {}).get("links", {})
        for i, item in enumerate(links.values()):
            if "position" not in item:
                item["position"] = i
        athlete["medias_sorted"] = sorted(
            links.values(), key=lambda x: x.get("position", 999)
        )

        editable = (session.get("user_email") is not None)
        owners = [o.email for o in ath.owners]
        is_claimable = owners == ["import@fu19.org"]
    finally:
        db.close()

    return render_template("fiche_athlete.html",
                           athlete=athlete,
                           current_user_email=session.get("user_email"),
                           editable=editable,
                           is_claimable=is_claimable)

@app.route("/fiche/<athlete_id>/edit")
def fiche_edit(athlete_id):
    user_email = session.get("user_email")
    if not user_email:
        flash("🔒 Connectez-vous pour accéder à l'édition.", "warning")
        return redirect(url_for("fiches_list"))

    db = SessionLocal()
    try:
        ath = get_athlete_or_404(db, athlete_id)
        if not ath:
            return redirect(url_for("fiches_list"))

        # Vérification ownership
        is_admin = user_email.strip().lower() in ADMIN_EMAILS
        is_owner = any(o.email == user_email.strip().lower() for o in ath.owners)

        if not is_admin and not is_owner:
            flash("⛔ Vous n'êtes pas autorisé à éditer cette fiche.", "error")
            return redirect(url_for("fiches_list"))

        athlete = athlete_to_dict(ath)
    finally:
        db.close()

    return render_template("fiche_edit.html",
                           athlete=athlete,
                           current_user_email=user_email)

# ==============================================================================
# ROUTES — AUTH
# ==============================================================================

@app.route("/auth/login", methods=["POST"])
def auth_login():
    """Demande d'envoi de magic link (API JSON)."""
    data  = request.get_json()
    email = data.get("email", "").strip().lower()
    if not email:
        return {"status": "ERROR", "message": "Email manquant."}, 400

    db = SessionLocal()
    try:
        linker    = MagicLinker()
        magic_url = linker.request_login(db, email)
        result    = send_magic_link(email, magic_url)
        if result["status"] == "ERROR":
            return {"status": "ERROR", "message": result["message"]}, 500
        return {"status": "SUCCESS"}
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}, 500
    finally:
        db.close()


@app.route("/auth/verify")
def auth_verify():
    token = request.args.get("token")
    email = request.args.get("email", "").strip().lower()

    db = SessionLocal()
    try:
        linker = MagicLinker()
        is_authenticated = linker.process_landing(db, email, token)

        if not is_authenticated:
            flash("❌ Lien de validation invalide, expiré ou déjà utilisé.", "error")
            return redirect(url_for("fiches_list"))

        # Session ouverte
        session["user_email"] = email

        # Fiche en soute ?
        pending = session.pop("pending_fiche_data", None)

        if pending and pending.get("creator_email") == email:
            try:
                result = FicheFactory.assemble_and_store(
                    db,
                    raw_data=pending,
                    owner_email=email,
                    role=pending.get("role", "creator")
                )
                if result["status"] == "SUCCESS":
                    flash(
                        f"⚡ Connexion réussie ! La fiche de {pending['prenom']} "
                        f"a été créée avec succès.",
                        "success"
                    )
                    return redirect(url_for("fiche_edit", athlete_id=result["athlete_id"]))
                else:
                    flash(
                        f"⚠️ Authentifié, mais erreur création fiche : {result['message']}",
                        "warning"
                    )
            except Exception as e:
                flash(f"❌ Erreur création fiche : {str(e)}", "error")
        else:
            flash("⚡ Connexion réussie. Bienvenue sur votre espace.", "success")

    except Exception as e:
        flash(f"❌ Erreur d'activation de session : {str(e)}", "error")
    finally:
        db.close()

    return redirect(url_for("fiches_list"))


@app.route("/auth/logout")
def auth_logout():
    session.clear()
    flash("👋 Vous êtes déconnecté.", "success")
    return redirect(url_for("fiches_list"))

# ==============================================================================
# ROUTES — REVENDICATION & SIGNALEMENT
# À coller après auth_logout() et avant create_fiche()
# ==============================================================================

# ------------------------------------------------------------------------------
# ÉTAPE 1/2 REVENDICATION — Formulaire + validation légale + magic link
# ------------------------------------------------------------------------------
@app.route("/fiche/<athlete_id>/revendiquer", methods=["GET", "POST"])
def revendiquer_fiche(athlete_id):
    """
    GET  → Affiche le formulaire de revendication (legal_filters + email).
    POST → Valide les conditions légales, génère un magic link spécifique
           à la revendication et l'envoie au demandeur.
           La fiche n'est PAS modifiée tant que le lien n'a pas été cliqué.
    """
    db = SessionLocal()
    try:
        ath = get_athlete_or_404(db, athlete_id)
        if not ath:
            return redirect(url_for("fiches_list"))
        athlete = athlete_to_dict(ath)

        # Vérification : la fiche est-elle revendiquable ?
        # Une fiche n'est revendiquable que si son seul owner est import@fu19.org
        owners = [o.email for o in ath.owners]
        is_claimable = owners == ["import@fu19.org"]

        if not is_claimable:
            flash("⛔ Cette fiche est déjà rattachée à un propriétaire légal.", "error")
            return redirect(url_for("fiche_athlete", athlete_id=athlete_id))

    finally:
        db.close()

    if request.method == "GET":
        return render_template(
            "revendiquer_fiche.html",
            athlete=athlete,
            current_user_email=session.get("user_email")
        )

    # ── POST : validation légale ───────────────────────────────────────────────
    form_data = {
        "parental_consent": request.form.get("parental_consent"),
        "parent_full_name": request.form.get("parent_full_name"),
        "user_role":        request.form.get("user_role"),
        "email":            request.form.get("email", "").strip().lower(),
    }

    is_legal, legal_msg = validate_legal_requirements(form_data)
    if not is_legal:
        flash(f"❌ {legal_msg}", "error")
        return render_template(
            "revendiquer_fiche.html",
            athlete=athlete,
            form_data=form_data,
            current_user_email=session.get("user_email")
        )

    # ── Génération du magic link de revendication ──────────────────────────────
    # On réutilise MagicLinker (même mécanique que l'auth classique)
    # mais l'URL cible est /auth/claim au lieu de /auth/verify,
    # ce qui permet de distinguer les deux flux à l'arrivée.
    db = SessionLocal()
    try:
        linker    = MagicLinker()
        email     = form_data["email"]
        token_url = linker.request_login(db, email)

        # Reconstruction de l'URL vers /auth/claim avec athlete_id en paramètre
        # Le token et l'email sont déjà dans token_url (/auth/verify?token=...&email=...)
        # On remplace /auth/verify par /auth/claim et on ajoute athlete_id
        from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
        parsed   = urlparse(token_url)
        params   = parse_qs(parsed.query)
        token    = params["token"][0]
        from core.config import BASE_URL as _BASE_URL
        claim_url = (
            f"{_BASE_URL}/auth/claim"
            f"?token={token}&email={email}&athlete_id={athlete_id}"
        )

        # Mise en soute des données de revendication dans la session
        # (rôle et signature légale à conserver pour la table d'association)
        session["pending_claim"] = {
            "athlete_id":    athlete_id,
            "claimer_email": email,
            "role":          form_data["user_role"],
            "declarant":     form_data["parent_full_name"],
        }

        # Envoi de l'email via notifier.py
        athlete_name = f"{athlete['prenom']} {athlete['nom']}"
        result = send_claim_magic_link(email, athlete_name, claim_url)

        if result["status"] == "ERROR":
            flash(f"❌ Erreur envoi email : {result['message']}", "error")
            return render_template(
                "revendiquer_fiche.html",
                athlete=athlete,
                form_data=form_data,
                current_user_email=session.get("user_email")
            )

        flash(
            f"📩 Un lien de revendication a été envoyé à {email}. "
            f"Cliquez dessus dans les 15 minutes pour finaliser.",
            "success"
        )

    except Exception as e:
        flash(f"❌ Erreur : {str(e)}", "error")
    finally:
        db.close()

    return redirect(url_for("fiche_athlete", athlete_id=athlete_id))


# ------------------------------------------------------------------------------
# ÉTAPE 2/2 REVENDICATION — Consommation du magic link
# ------------------------------------------------------------------------------
@app.route("/auth/claim")
def auth_claim():
    """
    Endpoint de réception du magic link de revendication.
    Vérifie le token, rattache le nouveau owner légal à la fiche,
    retire import@fu19.org de la table d'association.
    """
    token      = request.args.get("token")
    email      = request.args.get("email", "").strip().lower()
    athlete_id = request.args.get("athlete_id", "").strip()

    if not token or not email or not athlete_id:
        flash("❌ Lien de revendication invalide ou incomplet.", "error")
        return redirect(url_for("fiches_list"))

    db = SessionLocal()
    try:
        # Vérification et consommation du token (anti-replay intégré dans MagicLinker)
        linker = MagicLinker()
        is_valid = linker.process_landing(db, email, token)

        if not is_valid:
            flash("❌ Lien invalide, expiré ou déjà utilisé.", "error")
            return redirect(url_for("fiches_list"))

        # Récupération de la fiche et vérification qu'elle est encore revendiquable
        ath = db.query(Athlete).filter(Athlete.id == athlete_id).first()
        if not ath:
            flash("❌ Fiche introuvable.", "error")
            return redirect(url_for("fiches_list"))

        owners = [o.email for o in ath.owners]
        if owners != ["import@fu19.org"]:
            flash("⚠️ Cette fiche a déjà été revendiquée.", "warning")
            return redirect(url_for("fiche_athlete", athlete_id=athlete_id))

        # Récupération du rôle depuis la session en soute
        pending = session.pop("pending_claim", {})
        role    = pending.get("role", "parent")

        # Rattachement du nouveau owner légal via la table d'association
        from data.queries import get_or_create_user
        new_owner = get_or_create_user(db, email)
        ath.owners.append(new_owner)

        # Mise à jour du rôle dans la table athlete_owners
        db.execute(
            athlete_owners.update()
            .where(athlete_owners.c.user_email == email)
            .where(athlete_owners.c.athlete_id == athlete_id)
            .values(role=role)
        )

        # Retrait de import@fu19.org de la table d'association
        # (suppression de la ligne dans athlete_owners, pas du User)
        db.execute(
            athlete_owners.delete()
            .where(athlete_owners.c.user_email == "import@fu19.org")
            .where(athlete_owners.c.athlete_id == athlete_id)
        )

        db.commit()

        # Ouverture de la session utilisateur
        session["user_email"] = email

        flash(
            f"✅ Fiche de {ath.prenom} {ath.nom} revendiquée avec succès ! "
            f"Vous pouvez maintenant l'enrichir.",
            "success"
        )
        return redirect(url_for("fiche_edit", athlete_id=athlete_id))

    except Exception as e:
        db.rollback()
        flash(f"❌ Erreur lors de la revendication : {str(e)}", "error")
        return redirect(url_for("fiches_list"))
    finally:
        db.close()


# ------------------------------------------------------------------------------
# ÉTAPE 1/2 SIGNALEMENT — Formulaire + magic link de vérification reporter
# ------------------------------------------------------------------------------
@app.route("/fiche/<athlete_id>/signaler", methods=["GET", "POST"])
def signaler_fiche(athlete_id):
    """
    GET  → Affiche le formulaire de signalement (motif + détail + email).
    POST → Génère un magic link envoyé au reporter pour vérifier son identité.
           La notification admin n'est envoyée qu'après clic sur le lien,
           ce qui évite les signalements anonymes ou automatisés.
    """
    db = SessionLocal()
    try:
        ath = get_athlete_or_404(db, athlete_id)
        if not ath:
            return redirect(url_for("fiches_list"))
        athlete = athlete_to_dict(ath)
    finally:
        db.close()

    # Import des motifs depuis notifier.py pour les afficher dans le template
    from processors.notifier import REPORT_REASONS

    if request.method == "GET":
        return render_template(
            "signaler_fiche.html",
            athlete=athlete,
            report_reasons=REPORT_REASONS,
            current_user_email=session.get("user_email")
        )

    # ── POST : collecte du signalement + envoi magic link ─────────────────────
    email      = request.form.get("email", "").strip().lower()
    reason_key = request.form.get("reason_key", "autre")
    detail     = request.form.get("detail", "").strip()

    if not email:
        flash("❌ Votre adresse e-mail est obligatoire pour signaler.", "error")
        return render_template(
            "signaler_fiche.html",
            athlete=athlete,
            report_reasons=REPORT_REASONS,
            current_user_email=session.get("user_email")
        )

    # Mise en soute du signalement (envoyé aux admins seulement après vérification)
    session["pending_report"] = {
        "athlete_id":     athlete_id,
        "athlete_name":   f"{athlete['prenom']} {athlete['nom']}",
        "reason_key":     reason_key,
        "detail":         detail,
        "reporter_email": email,
    }

    db = SessionLocal()
    try:
        # Magic link standard — l'URL cible est /auth/report
        linker    = MagicLinker()
        token_url = linker.request_login(db, email)

        from urllib.parse import urlparse, parse_qs
        from core.config import BASE_URL as _BASE_URL
        parsed   = urlparse(token_url)
        params   = parse_qs(parsed.query)
        token    = params["token"][0]
        report_url = (
            f"{_BASE_URL}/auth/report"
            f"?token={token}&email={email}"
        )

        # Envoi du magic link au reporter via emailer classique
        result = send_magic_link(email, report_url)
        if result["status"] == "ERROR":
            flash(f"❌ Erreur envoi email : {result['message']}", "error")
            return render_template(
                "signaler_fiche.html",
                athlete=athlete,
                report_reasons=REPORT_REASONS,
                current_user_email=session.get("user_email")
            )

        flash(
            f"📩 Un lien de confirmation a été envoyé à {email}. "
            f"Cliquez dessus pour finaliser votre signalement.",
            "success"
        )

    except Exception as e:
        flash(f"❌ Erreur : {str(e)}", "error")
    finally:
        db.close()

    return redirect(url_for("fiche_athlete", athlete_id=athlete_id))


# ------------------------------------------------------------------------------
# ÉTAPE 2/2 SIGNALEMENT — Consommation du magic link + notification admins
# ------------------------------------------------------------------------------
@app.route("/auth/report")
def auth_report():
    """
    Endpoint de réception du magic link de signalement.
    Vérifie le token, puis envoie la notification aux admins via notifier.py.
    La fiche n'est jamais modifiée automatiquement — suivi humain attendu.
    """
    token = request.args.get("token")
    email = request.args.get("email", "").strip().lower()

    if not token or not email:
        flash("❌ Lien de signalement invalide.", "error")
        return redirect(url_for("fiches_list"))

    db = SessionLocal()
    try:
        linker   = MagicLinker()
        is_valid = linker.process_landing(db, email, token)

        if not is_valid:
            flash("❌ Lien invalide, expiré ou déjà utilisé.", "error")
            return redirect(url_for("fiches_list"))

        # Récupération du signalement en soute
        pending = session.pop("pending_report", None)

        if not pending:
            # Cas rare : session expirée entre le formulaire et le clic
            flash(
                "⚠️ Session expirée. Merci de recommencer votre signalement.",
                "warning"
            )
            return redirect(url_for("fiches_list"))

        # Envoi de la notification aux admins via notifier.py
        result = send_report_notification(
            athlete_id    = pending["athlete_id"],
            athlete_name  = pending["athlete_name"],
            reason_key    = pending["reason_key"],
            detail        = pending["detail"],
            reporter_email= pending["reporter_email"],
        )

        if result["status"] == "SUCCESS":
            flash(
                "✅ Votre signalement a été transmis à l'équipe fU19. "
                "Un suivi humain sera effectué dans les meilleurs délais.",
                "success"
            )
        elif result["status"] == "PARTIAL":
            # Certains admins ont reçu, pas tous — on confirme quand même au reporter
            flash(
                "✅ Signalement transmis. Merci pour votre vigilance.",
                "success"
            )
        else:
            flash(
                "⚠️ Votre signalement a été enregistré mais l'envoi a échoué. "
                "Contactez directement contact@fu19.org.",
                "warning"
            )

        return redirect(url_for("fiche_athlete", athlete_id=pending["athlete_id"]))

    except Exception as e:
        flash(f"❌ Erreur : {str(e)}", "error")
        return redirect(url_for("fiches_list"))
    finally:
        db.close()



# ==============================================================================
# ROUTES — CRÉATION
# ==============================================================================

@app.route("/creer", methods=["GET", "POST"])
def create_fiche():
    if request.method == "GET":
        return render_template(
            "create_fiche.html",
            current_user_email=session.get("user_email")
        )

    # 1. Extraction des données du formulaire
    raw_data = {
        "nom":              request.form.get("nom", "").strip(),
        "prenom":           request.form.get("prenom", "").strip(),
        "date_naissance":   request.form.get("date_naissance", "").strip(),
        "sexe":             request.form.get("sexe", "M").strip(),
        "nationalite":      request.form.get("nationalite", "FR").strip(),
        "parental_consent": request.form.get("parental_consent"),
        "parent_full_name": request.form.get("parent_full_name"),
        "user_role":        request.form.get("user_role"),
        "email":            request.form.get("email", "").strip().lower(),
    }

    # 2. Filtre légal
    is_legal_valid, legal_msg = validate_legal_requirements(raw_data)
    if not is_legal_valid:
        flash(f"❌ {legal_msg}", "error")
        return render_template(
            "create_fiche.html",
            form_data=raw_data,
            current_user_email=session.get("user_email")
        )

    # 3. Magic link + mise en soute
    db = SessionLocal()
    try:
        linker    = MagicLinker()
        magic_url = linker.request_login(db, raw_data["email"])

        # Envoi email réel via emailer.py
        email_result = send_magic_link(raw_data["email"], magic_url)
        if email_result["status"] == "ERROR":
            flash(f"❌ Erreur envoi email : {email_result['message']}", "error")
            return render_template(
                "create_fiche.html",
                form_data=raw_data,
                current_user_email=session.get("user_email")
            )

        # Données en soute — créées en BDD uniquement après clic du lien
        session["pending_fiche_data"] = {
            "nom":           raw_data["nom"],
            "prenom":        raw_data["prenom"],
            "date_naissance": raw_data["date_naissance"],
            "sexe":          raw_data["sexe"],
            "nationalite":   raw_data["nationalite"],
            "creator_email": raw_data["email"],
            "role":          raw_data["user_role"],
            "club": "", "ville": "", "federation": "", "uci_number": "",
        }

        flash(
            f"📩 Un lien de validation a été envoyé à {raw_data['email']}. "
            f"Cliquez dessus dans les 15 minutes pour finaliser la création.",
            "success"
        )

    except Exception as e:
        flash(f"❌ Erreur lors de la préparation de l'accès : {str(e)}", "error")
        return render_template(
            "create_fiche.html",
            form_data=raw_data,
            current_user_email=session.get("user_email")
        )
    finally:
        db.close()

    return redirect(url_for("fiches_list"))


# ==============================================================================
# ROUTES — MISES À JOUR PAR BLOC
# ==============================================================================

@app.route("/fiche/<athlete_id>/update/identite", methods=["POST"])
def update_identite(athlete_id):
    if not session.get("user_email"):
        flash("🔒 Connectez-vous pour modifier une fiche.", "warning")
        return redirect(url_for("fiches_list"))

    updated = {
        "nom":            request.form.get("nom", "").strip(),
        "prenom":         request.form.get("prenom", "").strip(),
        "sexe":           request.form.get("sexe", "").strip(),
        "date_naissance": request.form.get("date_naissance", "").strip(),
        "nationalite":    request.form.get("nationalite", "").strip(),
        "uci_id_data": {
            "federation": request.form.get("federation", "").strip(),
            "club":       request.form.get("club", "").strip(),
            "ville":      request.form.get("ville", "").strip(),
            "number":     request.form.get("uci_number", "").strip(),
        }
    }
    db = SessionLocal()
    try:
        result = FicheFactory.update_athlete_profile(db, athlete_id, updated)
    finally:
        db.close()

    flash(
        "✅ Identité mise à jour." if result["status"] == "SUCCESS" else f"❌ {result['message']}",
        "success" if result["status"] == "SUCCESS" else "error"
    )
    return redirect(url_for("fiche_edit", athlete_id=athlete_id))


@app.route("/fiche/<athlete_id>/update/poids", methods=["POST"])
def update_poids(athlete_id):
    if not session.get("user_email"):
        flash("🔒 Connectez-vous pour modifier une fiche.", "warning")
        return redirect(url_for("fiches_list"))

    try:
        poids = float(request.form.get("poids", "0").strip())
    except ValueError:
        flash("❌ Poids invalide.", "error")
        return redirect(url_for("fiche_edit", athlete_id=athlete_id))

    db = SessionLocal()
    try:
        result = FicheFactory.update_athlete_profile(db, athlete_id, {
            "donnees_performance": {"poids": poids}
        })
    finally:
        db.close()

    flash(
        "✅ Poids mis à jour." if result["status"] == "SUCCESS" else f"❌ {result['message']}",
        "success" if result["status"] == "SUCCESS" else "error"
    )
    return redirect(url_for("fiche_edit", athlete_id=athlete_id))


@app.route("/fiche/<athlete_id>/update/profil", methods=["POST"])
def update_profil(athlete_id):
    if not session.get("user_email"):
        flash("🔒 Connectez-vous pour modifier une fiche.", "warning")
        return redirect(url_for("fiches_list"))

    profil = request.form.get("profil_manuel", "").strip()
    db = SessionLocal()
    try:
        result = FicheFactory.update_athlete_profile(db, athlete_id, {
            "donnees_performance": {"profil_manuel": profil}
        })
    finally:
        db.close()

    flash(
        "✅ Profil mis à jour." if result["status"] == "SUCCESS" else f"❌ {result['message']}",
        "success" if result["status"] == "SUCCESS" else "error"
    )
    return redirect(url_for("fiche_edit", athlete_id=athlete_id))


@app.route("/fiche/<athlete_id>/update/medias", methods=["POST"])
def update_medias(athlete_id):
    if not session.get("user_email"):
        flash("🔒 Connectez-vous pour modifier une fiche.", "warning")
        return redirect(url_for("fiches_list"))

    media_type  = request.form.get("media_type", "autre")
    media_url   = request.form.get("media_url", "").strip()
    media_label = request.form.get("media_label", "").strip() or media_url

    db = SessionLocal()
    try:
        ath = get_athlete_or_404(db, athlete_id)
        if ath:
            medias = dict(ath.medias) if ath.medias else {"links": {}}
            medias.setdefault("links", {})
            key = f"{media_type}_{media_label}"
            medias["links"][key] = {
                "url":      media_url,
                "label":    media_label,
                "type":     media_type,
                "position": len(medias["links"])
            }
            ath.medias = medias
            flag_modified(ath, "medias")
            db.commit()
            flash("✅ Lien ajouté.", "success")
    except Exception as e:
        db.rollback()
        flash(f"❌ Erreur : {str(e)}", "error")
    finally:
        db.close()

    return redirect(url_for("fiche_edit", athlete_id=athlete_id))


@app.route("/fiche/<athlete_id>/update/medias_bulk", methods=["POST"])
def update_medias_bulk(athlete_id):
    """Reçoit un tableau JSON de médias avec position et remplace links."""
    if not session.get("user_email"):
        return {"status": "error", "message": "Non connecté"}, 401

    data = request.get_json()
    if not data or not isinstance(data, list):
        flash("Données invalides", "error")
        return redirect(url_for("fiche_edit", athlete_id=athlete_id))

    new_links = {}
    for idx, item in enumerate(data):
        key = f"{item.get('type','autre')}_{item.get('label','')}"
        new_links[key] = {
            "url":       item["url"],
            "label":     item.get("label", ""),
            "type":      item.get("type", "autre"),
            "position":  idx,
            "platform":  item.get("platform"),
            "title":     item.get("title"),
            "thumbnail": item.get("thumbnail")
        }

    db = SessionLocal()
    try:
        ath = get_athlete_or_404(db, athlete_id)
        if ath:
            medias = dict(ath.medias) if ath.medias else {"links": {}, "galerie": []}
            medias["links"] = new_links
            ath.medias = medias
            flag_modified(ath, "medias")
            db.commit()
            flash("✅ Médias mis à jour.", "success")
    except Exception as e:
        db.rollback()
        flash(f"❌ Erreur : {str(e)}", "error")
    finally:
        db.close()

    return redirect(url_for("fiche_edit", athlete_id=athlete_id))


# ==============================================================================
# ROUTES — PALMARÈS
# ==============================================================================

@app.route("/fiche/<athlete_id>/palmares/add", methods=["POST"])
def palmares_add(athlete_id):
    if not session.get("user_email"):
        flash("🔒 Connectez-vous pour modifier une fiche.", "warning")
        return redirect(url_for("fiches_list"))

    entry = {
        "classement": request.form.get("classement", "").strip(),
        "course":     request.form.get("course", "").strip(),
        "date":       request.form.get("date", "").strip(),
        "categorie":  request.form.get("categorie", "").strip(),
        "certified":  False,
    }
    db = SessionLocal()
    try:
        ath = get_athlete_or_404(db, athlete_id)
        if ath:
            palmares = list(ath.palmares) if ath.palmares else []
            palmares.append(entry)
            ath.palmares = palmares
            flag_modified(ath, "palmares")
            db.commit()
            flash("✅ Résultat ajouté au palmarès.", "success")
    except Exception as e:
        db.rollback()
        flash(f"❌ Erreur : {str(e)}", "error")
    finally:
        db.close()

    return redirect(url_for("fiche_edit", athlete_id=athlete_id))

@app.route("/fiche/<athlete_id>/palmares/delete/<int:index>", methods=["POST"])
def palmares_delete(athlete_id, index):
    """Suppression d'une ligne de palmarès par index — avec tri identique au template."""
    if not session.get("user_email"):
        flash("🔒 Connectez-vous pour modifier une fiche.", "warning")
        return redirect(url_for("fiches_list"))

    db = SessionLocal()
    try:
        ath = get_athlete_or_404(db, athlete_id)
        if ath:
            # Récupération et tri exactement comme dans le template
            palmares_raw = list(ath.palmares) if ath.palmares else []
            # Tri par date décroissante (même principe que le template :
            # {% for result in athlete.palmares | sort(attribute='date', reverse=True) %})
            palmares_sorted = sorted(palmares_raw,
                                     key=lambda x: x.get("date", ""),
                                     reverse=True)

            if 0 <= index < len(palmares_sorted):
                # On retire l'élément de la liste triée, mais il faut ensuite
                # reconstruire la liste originale sans cet élément.
                # On peut plutôt supprimer de la liste brute en retrouvant l'élément.
                # Pour éviter des problèmes de doublons, on va plutôt reconstruire
                # une nouvelle liste sans l'élément à l'index donné.
                # Méthode simple : on parcourt la liste triée, on garde tout sauf l'index.
                new_palmares = [item for i, item in enumerate(palmares_sorted) if i != index]
                # On veut préserver l'ordre original ? Pas nécessaire car le template
                # triera toujours. On peut directement sauvegarder la liste non triée,
                # mais c'est plus propre de conserver l'ordre tel quel.
                # On va simplement sauvegarder la liste sans l'élément (ordre de tri conservé,
                # mais de toute façon le template triera à l'affichage).
                ath.palmares = new_palmares
                flag_modified(ath, "palmares")
                db.commit()
                flash("🗑️ Résultat supprimé.", "success")
            else:
                flash("❌ Index invalide.", "error")
    except Exception as e:
        db.rollback()
        flash(f"❌ Erreur : {str(e)}", "error")
    finally:
        db.close()

    return redirect(url_for("fiche_edit", athlete_id=athlete_id))


# ==============================================================================
# ROUTES — MÉDIAS
# ==============================================================================

@app.route("/fiche/<athlete_id>/media/delete", methods=["POST"])
def delete_media(athlete_id):
    if not session.get("user_email"):
        flash("🔒 Connectez-vous pour modifier une fiche.", "warning")
        return redirect(url_for("fiches_list"))

    key = request.form.get("key")
    if not key:
        flash("Clé manquante.", "error")
        return redirect(url_for("fiche_edit", athlete_id=athlete_id))

    db = SessionLocal()
    try:
        ath = get_athlete_or_404(db, athlete_id)
        if ath:
            medias = dict(ath.medias) if ath.medias else {"links": {}}
            if key in medias.get("links", {}):
                del medias["links"][key]
                ath.medias = medias
                flag_modified(ath, "medias")
                db.commit()
                flash("🗑️ Lien supprimé.", "success")
            else:
                flash("❌ Lien introuvable.", "error")
    except Exception as e:
        db.rollback()
        flash(f"❌ Erreur : {str(e)}", "error")
    finally:
        db.close()

    return redirect(url_for("fiche_edit", athlete_id=athlete_id))


# ==============================================================================
# ROUTES — SUPPRESSION FICHE
# ==============================================================================

@app.route("/fiche/<athlete_id>/supprimer", methods=["POST"])
def supprimer_fiche(athlete_id):
    if not session.get("user_email"):
        flash("🔒 Connectez-vous pour supprimer une fiche.", "warning")
        return redirect(url_for("fiches_list"))

    db = SessionLocal()
    try:
        ath = db.query(Athlete).filter(Athlete.id == athlete_id).first()
        if ath:
            db.delete(ath)
            db.commit()
            athlete_dir = PROFILES_DIR / athlete_id
            if athlete_dir.exists():
                shutil.rmtree(str(athlete_dir))
            flash("🗑️ Fiche supprimée.", "success")
        else:
            flash("❌ Fiche introuvable.", "error")
    except Exception as e:
        db.rollback()
        flash(f"❌ Erreur : {str(e)}", "error")
    finally:
        db.close()

    return redirect(url_for("fiches_list"))


# ==============================================================================
# ROUTES — UPLOADS
# ==============================================================================

@app.route("/fiche/<athlete_id>/upload/photo", methods=["POST"])
def upload_photo(athlete_id):
    """Route legacy conservée — redirige vers le chatbot avatar."""
    flash("📸 Utilisez le chatbot Avatar pour personnaliser l'avatar.", "warning")
    return redirect(url_for("fiche_edit", athlete_id=athlete_id))


@app.route("/fiche/<athlete_id>/upload/fit", methods=["POST"])
def upload_fit(athlete_id):
    """
    Pipeline FIT multi-fichiers :
      1. Validation fichiers
      2. Validation poids (bloquant)
      3. Sauvegarde de chaque fichier dans le profil
      4. fit_parser  → fit_analysis.json  (sur TOUS les .fit du dossier)
      5. metrics_grapher → rider_metrics.png
      6. Mise à jour BDD (donnees_performance)
    """
    if not session.get("user_email"):
        flash("🔒 Connectez-vous pour importer des fichiers.", "warning")
        return redirect(url_for("fiches_list"))

    # 1. Validation fichiers
    files       = request.files.getlist("fit_file")
    valid_files = [f for f in files if f and allowed_file(f.filename, ALLOWED_FIT_EXTENSIONS)]
    if not valid_files:
        flash("❌ Aucun fichier .fit valide reçu.", "error")
        return redirect(url_for("fiche_edit", athlete_id=athlete_id))

    # 2. Validation poids
    db = SessionLocal()
    try:
        ath = get_athlete_or_404(db, athlete_id)
        if not ath:
            return redirect(url_for("fiches_list"))
        perf      = ath.donnees_performance or {}
        weight_kg = perf.get("poids")
        if not weight_kg or float(weight_kg) <= 0:
            flash(
                "⚠️ Poids manquant — renseignez le poids de l'athlète "
                "avant d'importer un fichier .fit. "
                "L'hélice metrics repose sur la puissance en W/kg : "
                "sans poids, aucun calcul ne peut être certifié.",
                "warning"
            )
            return redirect(url_for("fiche_edit", athlete_id=athlete_id))
        weight_kg = float(weight_kg)
    finally:
        db.close()

    # 3. Sauvegarde de chaque fichier
    fit_dir = PROFILES_DIR / athlete_id / "fit_files"
    fit_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for f in valid_files:
        from werkzeug.utils import secure_filename
        safe_name = secure_filename(f.filename)
        dest = fit_dir / safe_name
        f.save(str(dest))
        saved.append(safe_name)

    # 4. Parsing FIT sur TOUS les fichiers du dossier
    all_fit_files = sorted(fit_dir.glob("*.fit"))
    try:
        json_path = run_for_athlete(
            fit_path=all_fit_files,
            weight_kg=weight_kg,
            output_dir=PROFILES_DIR / athlete_id
        )
    except (ValueError, RuntimeError) as e:
        flash(f"❌ Erreur parsing FIT : {e}", "error")
        return redirect(url_for("fiche_edit", athlete_id=athlete_id))

    # 5. Génération rider_metrics.png
    png_path = PROFILES_DIR / athlete_id / "metrics" / "rider_metrics.png"
    try:
        data = load_analysis(json_path)
        generate_artichoke(data, png_path)
    except Exception as e:
        flash(f"❌ Erreur génération graphique : {e}", "error")
        return redirect(url_for("fiche_edit", athlete_id=athlete_id))

    # 6. Mise à jour BDD
    db = SessionLocal()
    try:
        ath  = db.query(Athlete).filter(Athlete.id == athlete_id).first()
        perf = dict(ath.donnees_performance or {})
        perf["metrics_certified"]     = True
        perf["metrics_png_path"]      = str(png_path)
        perf["derniers_fichiers_fit"] = [f.name for f in all_fit_files]
        ath.donnees_performance = perf
        flag_modified(ath, "donnees_performance")
        db.commit()
        n     = len(saved)
        label = "fichier importé" if n == 1 else "fichiers importés"
        flash(f"✅ {n} {label} — hélice metrics recalculée.", "success")
    except Exception as e:
        db.rollback()
        flash(f"❌ Erreur mise à jour BDD : {e}", "error")
    finally:
        db.close()

    return redirect(url_for("fiche_edit", athlete_id=athlete_id))


@app.route("/fiche/<athlete_id>/fit/delete/<filename>", methods=["POST"])
def fit_delete(athlete_id, filename):
    """
    Supprime un fichier .fit et relance le pipeline sur les restants.
    Si plus aucun fichier → décertification automatique.
    """
    if not session.get("user_email"):
        flash("🔒 Connectez-vous pour modifier une fiche.", "warning")
        return redirect(url_for("fiches_list"))

    from werkzeug.utils import secure_filename
    safe_name = secure_filename(filename)
    fit_dir   = PROFILES_DIR / athlete_id / "fit_files"
    target    = fit_dir / safe_name

    if target.exists():
        target.unlink()

    remaining = sorted(fit_dir.glob("*.fit"))

    db = SessionLocal()
    try:
        ath  = db.query(Athlete).filter(Athlete.id == athlete_id).first()
        perf = dict(ath.donnees_performance or {})

        if not remaining:
            perf["metrics_certified"]     = False
            perf["derniers_fichiers_fit"] = []
            ath.donnees_performance = perf
            flag_modified(ath, "donnees_performance")
            db.commit()
            flash("🗑 Fichier supprimé — aucun .fit restant, hélice décertifiée.", "warning")
            return redirect(url_for("fiche_edit", athlete_id=athlete_id))

        weight_kg = float(perf.get("poids", 0))
        if weight_kg <= 0:
            perf["derniers_fichiers_fit"] = [f.name for f in remaining]
            ath.donnees_performance = perf
            flag_modified(ath, "donnees_performance")
            db.commit()
            flash("🗑 Fichier supprimé — poids manquant, pipeline non relancé.", "warning")
            return redirect(url_for("fiche_edit", athlete_id=athlete_id))

        # Re-parsing
        try:
            json_path = run_for_athlete(
                fit_path=remaining,
                weight_kg=weight_kg,
                output_dir=PROFILES_DIR / athlete_id
            )
        except (ValueError, RuntimeError) as e:
            flash(f"❌ Erreur parsing FIT : {e}", "error")
            return redirect(url_for("fiche_edit", athlete_id=athlete_id))

        # Re-génération graphique
        png_path = PROFILES_DIR / athlete_id / "metrics" / "rider_metrics.png"
        try:
            data = load_analysis(json_path)
            generate_artichoke(data, png_path)
        except Exception as e:
            flash(f"❌ Erreur génération graphique : {e}", "error")
            return redirect(url_for("fiche_edit", athlete_id=athlete_id))

        perf["metrics_certified"]     = True
        perf["metrics_png_path"]      = str(png_path)
        perf["derniers_fichiers_fit"] = [f.name for f in remaining]
        ath.donnees_performance = perf
        flag_modified(ath, "donnees_performance")
        db.commit()
        flash(f"🗑 Fichier supprimé — hélice recalculée sur {len(remaining)} session(s).", "success")

    except Exception as e:
        db.rollback()
        flash(f"❌ Erreur mise à jour BDD : {e}", "error")
    finally:
        db.close()

    return redirect(url_for("fiche_edit", athlete_id=athlete_id))


# ==============================================================================
# ROUTES — PAGES SKILL (stubs d'attente)
# ==============================================================================

@app.route("/skilla")
def skill_a():
    return render_template("skill_a.html", current_user_email=session.get("user_email"))

@app.route("/skillb")
def skill_b():
    return render_template("skill_b.html", current_user_email=session.get("user_email"))

@app.route("/skillc")
def skill_c():
    return render_template("skill_c.html", current_user_email=session.get("user_email"))


# ==============================================================================
# ROUTE — SURVEILLANCE (stub — sera alimenté par tailer daemon)
# Retourne les 5 derniers athlete_id actifs au format JSON
# Cette route sera consommée par fiches_list en AJAX après intégration tailer
# ==============================================================================

@app.route("/surveillance")
def surveillance():
    """
    Stub de surveillance — retourne les 5 fiches les plus actives.
    Format JSON consommable par le frontend ou d'autres scripts.

    Sera remplacé par lecture des logs tailer quand le daemon sera actif.
    La signature JSON restera identique pour ne pas modifier les consommateurs.
    """
    db = SessionLocal()
    try:
        highlight_ids = get_highlight_ids(db, n=5)
        athletes = []
        for aid in highlight_ids:
            ath = db.query(Athlete).filter(Athlete.id == aid).first()
            if ath:
                athletes.append({
                    "id":     ath.id,
                    "nom":    ath.nom,
                    "prenom": ath.prenom,
                    "url":    f"/fiche/{ath.id}"
                })
    finally:
        db.close()

    from flask import jsonify
    return jsonify({"highlights": athletes})
# ==============================================================================
# LANCEMENT
# ==============================================================================
# Production : gunicorn --bind 127.0.0.1:8000 app:app
# Développement : python app.py
if __name__ == "__main__":
    app.run(debug=DEBUG, host="127.0.0.1", port=8000)
