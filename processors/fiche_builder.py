# ~/fjc/processors/fiche_builder.py
"""
FICHE BUILDER — Moteur de rendu batch

Rôle : lire la BDD et générer les fichiers HTML de toutes les fiches.
Délègue toute la logique de transformation à fiche_renderer.py.

Usage :
    cd ~/fjc
    python processors/fiche_builder.py
"""

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from data.database import SessionLocal
from data.models import Athlete
from processors.fiche_renderer import render_athlete_slots, athlete_to_dict
from web.webmaster import Webmaster


class FicheBuilder:
    """
    Construit le site statique complet depuis la BDD.

    PIPELINE :
        BDD → fiche_renderer → Webmaster → fichiers HTML sur disque

    Génère :
        - prototype_fiches_list.html       (liste de toutes les fiches)
        - prototype_fiche_<id>.html        (une fiche par athlète)
    """

    def __init__(self):
        self.webmaster = Webmaster()

    # ------------------------------------------------------------------
    # POINT D'ENTRÉE PRINCIPAL
    # ------------------------------------------------------------------

    def build_site_from_db(self):
        """Régénère l'intégralité du site depuis la BDD."""
        db = SessionLocal()
        try:
            athletes_raw = db.query(Athlete).filter(
                Athlete.status == "PUBLIC"
            ).all()

            if not athletes_raw:
                print("⚠️  [BUILDER] Base vide — aucune fiche à générer.")
                return

            print(f"📚 [BUILDER] {len(athletes_raw)} fiche(s) trouvée(s).")

            # 1. Génère la liste
            self._build_list(athletes_raw)

            # 2. Génère chaque fiche individuelle
            for ath in athletes_raw:
                self._build_fiche(ath)

            print("✅ [BUILDER] Site généré avec succès.")

        finally:
            db.close()

    # ------------------------------------------------------------------
    # LISTE DES FICHES
    # ------------------------------------------------------------------

    def _build_list(self, athletes_raw: list):
        """Génère prototype_fiches_list.html."""

        athletes_dicts = [athlete_to_dict(a) for a in athletes_raw]

        # Stats macro pour la sidebar
        nations = sorted(set(a["nationalite"] for a in athletes_dicts if a["nationalite"]))
        years   = sorted(set(a["junior_horizon"] for a in athletes_dicts if a["junior_horizon"]))

        stats = {
            "total":        len(athletes_dicts),
            "nb_M":         sum(1 for a in athletes_dicts if a["sexe"] == "M"),
            "nb_F":         sum(1 for a in athletes_dicts if a["sexe"] == "F"),
            "nb_nations":   len(nations),
            "nb_certified": sum(1 for a in athletes_dicts if a["photo_certified"]),
            "nations":      nations,
            "years":        years,
        }

        # En batch : toutes les fiches sont éditables (admin)
        user_athlete_ids = [a["id"] for a in athletes_dicts]

        self.webmaster.render_prototype(
            template_name="fiches_list.html",
            output_name="prototype_fiches_list.html",
            context={
                "athletes":          athletes_dicts,
                "stats":             stats,
                "user_athlete_ids":  user_athlete_ids,
                "current_user_email": "admin@fjc.fr",
            }
        )
        print("   ✓ prototype_fiches_list.html")

    # ------------------------------------------------------------------
    # FICHE INDIVIDUELLE
    # ------------------------------------------------------------------

    def _build_fiche(self, ath: Athlete):
        """Génère prototype_fiche_<id>.html pour un athlète."""

        athlete, meta_pills_html, infos_col_html, medias_html = render_athlete_slots(ath)

        self.webmaster.render_prototype(
            template_name="fiche_athlete.html",
            output_name=f"prototype_fiche_{ath.id}.html",
            context={
                "athlete":          athlete,
                "meta_pills_html":  meta_pills_html,
                "infos_col_html":   infos_col_html,
                "medias_html":      medias_html,
                "current_user_email": "admin@fjc.fr",
            }
        )
        print(f"   ✓ prototype_fiche_{ath.id}.html — {ath.prenom} {ath.nom}")

    # ------------------------------------------------------------------
    # REBUILD CIBLÉ — une seule fiche
    # ------------------------------------------------------------------

    def rebuild_fiche(self, athlete_id: str):
        """
        Régénère uniquement la fiche d'un athlète spécifique.
        Utile après un upload .fit ou une modification manuelle.

        Usage :
            FicheBuilder().rebuild_fiche("fjc_ath_260519_laza_a3f2")
        """
        db = SessionLocal()
        try:
            ath = db.query(Athlete).filter(Athlete.id == athlete_id).first()
            if not ath:
                print(f"❌ [BUILDER] Athlète {athlete_id} introuvable.")
                return
            self._build_fiche(ath)
            print(f"✅ [BUILDER] Fiche {athlete_id} reconstruite.")
        finally:
            db.close()


# ==============================================================================
# LANCEMENT DIRECT
# ==============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="FJC Fiche Builder")
    parser.add_argument(
        "--id",
        type=str,
        default=None,
        help="Reconstruire une seule fiche (athlete_id). Omis = rebuild complet."
    )
    args = parser.parse_args()

    builder = FicheBuilder()

    if args.id:
        print(f"🔨 [BUILDER] Rebuild ciblé : {args.id}")
        builder.rebuild_fiche(args.id)
    else:
        print("🔨 [BUILDER] Rebuild complet du site...")
        builder.build_site_from_db()
