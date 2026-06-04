# ~/fjc/app.py
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, send_file, session
)
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


# ==============================================================================
# ROUTES — NAVIGATION
# ==============================================================================

@app.route("/")
def index():
    return redirect(url_for("fiches_list"))

@app.route("/fiches")
def fiches_list():
    db = SessionLocal()
    try:
        athletes_raw     = db.query(Athlete).filter(Athlete.status == "PUBLIC").all()
        athletes         = [athlete_to_dict(a) for a in athletes_raw]
        stats            = build_stats(athletes)
        user_email       = session.get("user_email")
        
        user_athlete_ids = []
        if user_email:
            user_email_clean = user_email.strip().lower()
            
            # 👑 Si c'est l'admin suprême, il possède TOUTES les fiches
            if user_email_clean in ADMIN_EMAILS:
                user_athlete_ids = [a["id"] for a in athletes]
            else:
                # Sinon, parcours classique pour les utilisateurs normaux
                user_data = get_user_dashboard_data(db, user_email_clean)
                if user_data and user_data.athletes:
                    user_athlete_ids = [a.id for a in user_data.athletes]
                
    finally:
        db.close()

    return render_template("fiches_list.html",
                           athletes=athletes,
                           stats=stats,
                           user_athlete_ids=user_athlete_ids,
                           current_user_email=user_email)


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
    finally:
        db.close()

    return render_template("fiche_athlete.html",
                           athlete=athlete,
                           current_user_email=session.get("user_email"),
                           editable=editable)

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
    """Suppression d'une ligne de palmarès par index — corrigé ORM."""
    if not session.get("user_email"):
        flash("🔒 Connectez-vous pour modifier une fiche.", "warning")
        return redirect(url_for("fiches_list"))

    db = SessionLocal()
    try:
        ath = get_athlete_or_404(db, athlete_id)
        if ath:
            palmares = list(ath.palmares) if ath.palmares else []
            if 0 <= index < len(palmares):
                palmares.pop(index)
                ath.palmares = palmares
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
# LANCEMENT
# ==============================================================================
# Production : gunicorn --bind 127.0.0.1:8000 app:app
# Développement : python app.py
if __name__ == "__main__":
    app.run(debug=DEBUG, host="127.0.0.1", port=8000)
