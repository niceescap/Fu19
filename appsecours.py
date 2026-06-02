# ~/fjc/app.py
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from core.config import (
    SECRET_KEY, TEMPLATES_DIR, STATIC_DIR,
    ALLOWED_PHOTO_EXTENSIONS, ALLOWED_FIT_EXTENSIONS,
    PROFILES_DIR, DEBUG
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
# ─────────────────────────────────────────────────────────────────────────────

app = Flask(
    __name__,
    template_folder=str(TEMPLATES_DIR),
    static_folder=str(STATIC_DIR)
)
app.secret_key = SECRET_KEY
app.register_blueprint(avatar_bp)

OWNER_EMAIL = "admin@fjc.fr"  # Hardcodé phase dev


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
# Sert les assets athlètes depuis PROFILES_DIR (hors static_folder Flask)
# Couvre : avatar.png, rider_metrics.png, tout futur asset par athlete_id
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
    """Liste de toutes les fiches publiques."""
    db = SessionLocal()
    try:
        athletes_raw     = db.query(Athlete).filter(Athlete.status == "PUBLIC").all()
        athletes         = [athlete_to_dict(a) for a in athletes_raw]
        stats            = build_stats(athletes)
        user_athlete_ids = [a["id"] for a in athletes]
    finally:
        db.close()

    return render_template("fiches_list.html",
                           athletes=athletes,
                           stats=stats,
                           user_athlete_ids=user_athlete_ids,
                           current_user_email=OWNER_EMAIL)


@app.route("/fiche/<athlete_id>")
def fiche_athlete(athlete_id):
    """Fiche publique d'un coureur."""
    db = SessionLocal()
    try:
        ath = get_athlete_or_404(db, athlete_id)
        if not ath:
            return redirect(url_for("fiches_list"))
        athlete, meta_pills_html, infos_col_html, medias_html = render_athlete_slots(ath)
    finally:
        db.close()

    return render_template("fiche_athlete.html",
                           athlete=athlete,
                           meta_pills_html=meta_pills_html,
                           infos_col_html=infos_col_html,
                           medias_html=medias_html,
                           current_user_email=OWNER_EMAIL)


@app.route("/fiche/<athlete_id>/edit")
def fiche_edit(athlete_id):
    """Page d'édition d'une fiche."""
    db = SessionLocal()
    try:
        ath = get_athlete_or_404(db, athlete_id)
        if not ath:
            return redirect(url_for("fiches_list"))
        athlete = athlete_to_dict(ath)
    finally:
        db.close()

    return render_template("fiche_edit.html",
                           athlete=athlete,
                           current_user_email=OWNER_EMAIL)


# ==============================================================================
# ROUTES — CRÉATION
# ==============================================================================

@app.route("/creer", methods=["GET", "POST"])
def create_fiche():
    if request.method == "GET":
        return render_template("create_fiche.html", current_user_email=OWNER_EMAIL)

    raw_data = {
        "nom":            request.form.get("nom", "").strip(),
        "prenom":         request.form.get("prenom", "").strip(),
        "date_naissance": request.form.get("date_naissance", "").strip(),
        "sexe":           request.form.get("sexe", "M").strip(),
        "nationalite":    request.form.get("nationalite", "FR").strip(),
        "club": "", "ville": "", "federation": "", "uci_number": "",
    }

    db = SessionLocal()
    try:
        result = FicheFactory.assemble_and_store(db, raw_data, OWNER_EMAIL, role="creator")
    finally:
        db.close()

    if result["status"] == "SUCCESS":
        flash("✅ Fiche créée ! Enrichissez-la maintenant.", "success")
        return redirect(url_for("fiche_edit", athlete_id=result["athlete_id"]))
    elif result["status"] == "DUPLICATE_FOUND":
        flash(f"⚠️ {result['message']}", "warning")
    else:
        flash(f"❌ Erreur : {result['message']}", "error")

    return render_template("create_fiche.html", current_user_email=OWNER_EMAIL, form_data=raw_data)


# ==============================================================================
# ROUTES — MISES À JOUR PAR BLOC
# ==============================================================================

@app.route("/fiche/<athlete_id>/update/identite", methods=["POST"])
def update_identite(athlete_id):
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

    flash("✅ Identité mise à jour." if result["status"] == "SUCCESS" else f"❌ {result['message']}",
          "success" if result["status"] == "SUCCESS" else "error")
    return redirect(url_for("fiche_edit", athlete_id=athlete_id))


@app.route("/fiche/<athlete_id>/update/poids", methods=["POST"])
def update_poids(athlete_id):
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

    flash("✅ Poids mis à jour." if result["status"] == "SUCCESS" else f"❌ {result['message']}",
          "success" if result["status"] == "SUCCESS" else "error")
    return redirect(url_for("fiche_edit", athlete_id=athlete_id))


@app.route("/fiche/<athlete_id>/update/profil", methods=["POST"])
def update_profil(athlete_id):
    profil = request.form.get("profil_manuel", "").strip()
    db = SessionLocal()
    try:
        result = FicheFactory.update_athlete_profile(db, athlete_id, {
            "donnees_performance": {"profil_manuel": profil}
        })
    finally:
        db.close()

    flash("✅ Profil mis à jour." if result["status"] == "SUCCESS" else f"❌ {result['message']}",
          "success" if result["status"] == "SUCCESS" else "error")
    return redirect(url_for("fiche_edit", athlete_id=athlete_id))


@app.route("/fiche/<athlete_id>/update/medias", methods=["POST"])
def update_medias(athlete_id):
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
                "url":   media_url,
                "label": media_label,
                "type":  media_type
            }
            ath.medias = medias
            db.commit()
            flash("✅ Lien ajouté.", "success")
    except Exception as e:
        db.rollback()
        flash(f"❌ Erreur : {str(e)}", "error")
    finally:
        db.close()

    return redirect(url_for("fiche_edit", athlete_id=athlete_id))


@app.route("/fiche/<athlete_id>/palmares/add", methods=["POST"])
def palmares_add(athlete_id):
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
            db.commit()
            flash("✅ Résultat ajouté au palmarès.", "success")
    except Exception as e:
        db.rollback()
        flash(f"❌ Erreur : {str(e)}", "error")
    finally:
        db.close()

    return redirect(url_for("fiche_edit", athlete_id=athlete_id))

@app.route("/fiche/<athlete_id>/supprimer", methods=["POST"])
def supprimer_fiche(athlete_id):
    db = SessionLocal()
    try:
        ath = db.query(Athlete).filter(Athlete.id == athlete_id).first()
        if ath:
            db.delete(ath)
            db.commit()
            # Suppression du coffre-fort physique
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
    """Route legacy conservée — redirige vers l'éditeur sans traitement."""
    flash("📸 Utilisez le chatbot Avatar pour personnaliser l'avatar.", "warning")
    return redirect(url_for("fiche_edit", athlete_id=athlete_id))


@app.route("/fiche/<athlete_id>/upload/fit", methods=["POST"])
def upload_fit(athlete_id):
    """
    Pipeline FIT complet :
      1. Validation fichier
      2. Validation poids (bloquant)
      3. Sauvegarde dans le profil
      4. fit_parser  → fit_analysis.json
      5. metrics_grapher → rider_metrics.png
      6. Mise à jour BDD (donnees_performance)
    """
    # 1. Validation fichier
    file = request.files.get("fit_file")
    if not file or not allowed_file(file.filename, ALLOWED_FIT_EXTENSIONS):
        flash("❌ Fichier .fit invalide ou manquant.", "error")
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

    # 3. Sauvegarde du fichier
    dest = PROFILES_DIR / athlete_id / "fit_files" / file.filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    file.save(str(dest))

    # 4. Parsing FIT → fit_analysis.json
    try:
        json_path = run_for_athlete(
            fit_path=dest,
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
        perf["metrics_certified"]    = True
        perf["metrics_png_path"]     = str(png_path)
        derniers = perf.get("derniers_fichiers_fit", [])
        if file.filename not in derniers:
            derniers.append(file.filename)
        perf["derniers_fichiers_fit"] = derniers
        ath.donnees_performance = perf
        db.commit()
        flash("✅ Pipeline FIT complet — hélice metrics certifiée.", "success")
    except Exception as e:
        db.rollback()
        flash(f"❌ Erreur mise à jour BDD : {e}", "error")
    finally:
        db.close()

    return redirect(url_for("fiche_edit", athlete_id=athlete_id))


# ==============================================================================
# LANCEMENT
# ==============================================================================

if __name__ == "__main__":
    app.run(debug=DEBUG, port=8000, host="0.0.0.0")
