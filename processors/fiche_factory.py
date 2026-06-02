# ~/fjc/processors/fiche_factory.py
import datetime
import sys
import secrets
import shutil
from pathlib import Path
from sqlalchemy.orm import Session

# Alignement des chemins pour Termux/VPS
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))

from core.config import PROFILES_DIR, STATIC_DIR   # <-- STATIC_DIR ajouté
from data.models import Athlete
from data.queries import create_athlete_with_owner


class FicheFactory:
    """
    L'Usine d'assemblage et de gestion du cycle de vie des profils athlètes.
    Centralise la création, la validation et la mise à jour des fiches.

    MÉTHODES PRINCIPALES :
        assemble_and_store()      → Création initiale de la fiche (Étape 1)
        update_athlete_profile()  → Modification manuelle ou automatique (Étape 2)
        attach_avatar()           → Branchement de l'avatar généré par avatar_chatbot_v2 (Étape 3)
    """

    # ------------------------------------------------------------------
    # UTILITAIRES INTERNES
    # ------------------------------------------------------------------

    @staticmethod
    def _calculate_junior_year(birth_date_str: str) -> int:
        """Calcule l'année d'accès à la catégorie Junior (l'année des 17 ans)."""
        try:
            birth_year = int(birth_date_str.split('-')[0])
            return birth_year + 17
        except (ValueError, AttributeError, IndexError):
            raise ValueError("Format de date invalide. Attendu : YYYY-MM-DD.")

    @staticmethod
    def _generate_athlete_id(nom: str) -> str:
        """Génère l'identifiant technique unique avec protection anti-collision."""
        timestamp = datetime.datetime.now().strftime('%y%m%d')
        nom_clean = nom.replace(' ', '').lower()[:4]
        suffix = secrets.token_hex(2)
        return f"fjc_ath_{timestamp}_{nom_clean}_{suffix}"

    @staticmethod
    def _provision_storage(athlete_id: str) -> bool:
        """Crée l'arborescence physique (Le Coffre-Fort local) pour l'athlète."""
        athlete_dir = PROFILES_DIR / athlete_id
        try:
            (athlete_dir / "fit_files").mkdir(parents=True, exist_ok=True)
            (athlete_dir / "images").mkdir(parents=True, exist_ok=True)
            (athlete_dir / "documents").mkdir(parents=True, exist_ok=True)
            return True
        except Exception as e:
            print(f"❌ [FACTORY] Erreur critique de stockage : {e}")
            return False

    # ------------------------------------------------------------------
    # ÉTAPE 1 — CRÉATION
    # ------------------------------------------------------------------

    @classmethod
    def assemble_and_store(cls, db: Session, raw_data: dict, owner_email: str, role: str = "creator") -> dict:
        """
        ÉTABLISSEMENT — Création initiale de la fiche athlète.

        Tamis anti-doublons sur (nom, prénom, date_naissance).
        Provisionne le coffre-fort physique et insère en BDD.

        Retourne :
            status SUCCESS        → athlete_id, horizon, message
            status DUPLICATE_FOUND → athlete_id existant
            status ERROR_*        → message d'erreur
        """
        nom            = raw_data.get('nom', '').strip().upper()
        prenom         = raw_data.get('prenom', '').strip().capitalize()
        date_naissance = raw_data.get('date_naissance', '').strip()
        sexe           = raw_data.get('sexe', '').strip().upper()

        # Tamis anti-doublons
        existing_athlete = db.query(Athlete).filter(
            Athlete.nom == nom,
            Athlete.prenom == prenom,
            Athlete.date_naissance == date_naissance
        ).first()

        if existing_athlete:
            return {
                "status": "DUPLICATE_FOUND",
                "message": f"Le profil de {prenom} {nom} existe déjà.",
                "athlete_id": existing_athlete.id
            }

        try:
            junior_horizon = cls._calculate_junior_year(date_naissance)
        except ValueError as e:
            return {"status": "ERROR_VALIDATION", "message": str(e)}

        athlete_id = cls._generate_athlete_id(nom)

        if not cls._provision_storage(athlete_id):
            return {"status": "ERROR_SYSTEM", "message": "Échec de création de l'espace de stockage."}

        # Structure du coffre-fort vierge
        # photo_status démarre à "AVATAR_PENDING" : avatar gris par défaut jusqu'au passage du chatbot
        athlete_record = {
            "id":             athlete_id,
            "nom":            nom,
            "prenom":         prenom,
            "date_naissance": date_naissance,
            "sexe":           sexe,
            "junior_horizon": junior_horizon,
            "nationalite":    raw_data.get('nationalite', 'FR').upper()[:2],
            "photo_status":   "AVATAR_PENDING",
            "uci_id_data": {
                "number":     raw_data.get('uci_number', ''),
                "status":     "UNVERIFIED",
                "federation": raw_data.get('federation', 'Inconnue'),
                "club":       raw_data.get('club', 'Indépendant'),
                "ville":      raw_data.get('ville', '-')
            },
            "palmares":             [],
            "donnees_performance":  {
                "derniers_fichiers_fit": [],
                "profil_puissance":     {"5s": 0, "1min": 0, "5min": 0, "20min": 0},
                "metriques_max":        {}
            },
            "medias":      {"links": {}, "galerie": []},
            "partenaires": []
        }

        try:
            create_athlete_with_owner(db, athlete_record, owner_email, role)
            print(f"✅ [FACTORY] Fiche {athlete_id} assemblée et scellée.")
            return {
                "status":     "SUCCESS",
                "athlete_id": athlete_id,
                "horizon":    junior_horizon,
                "message":    "Fiche établie avec succès."
            }
        except Exception as e:
            return {"status": "ERROR_DATABASE", "message": f"Échec d'écriture SQL : {str(e)}"}

    # ------------------------------------------------------------------
    # ÉTAPE 2 — ÉVOLUTION
    # ------------------------------------------------------------------

    @classmethod
    def update_athlete_profile(cls, db: Session, athlete_id: str, updated_data: dict) -> dict:
        """
        ÉVOLUTION — Modification manuelle ou automatique de la fiche.
        Fusionne proprement les modifications sans écraser les données saines.

        Gère :
            - Champs atomiques (nom, prénom, sexe, status, date_naissance)
            - Bloc JSON UCI / Club / Fédé  (fusion partielle)
            - Bloc JSON performance / watts (fusion partielle) — conserve poids, metrics, etc.
        """
        athlete = db.query(Athlete).filter(Athlete.id == athlete_id).first()
        if not athlete:
            return {"status": "NOT_FOUND", "message": f"Athlète {athlete_id} introuvable."}

        # Champs atomiques
        if 'nom' in updated_data:
            athlete.nom = updated_data['nom'].strip().upper()
        if 'prenom' in updated_data:
            athlete.prenom = updated_data['prenom'].strip().capitalize()
        if 'sexe' in updated_data:
            athlete.sexe = updated_data['sexe'].strip().upper()
        if 'status' in updated_data:
            athlete.status = updated_data['status']

        # Recalcul de l'horizon si correction de date de naissance
        if 'date_naissance' in updated_data:
            new_date = updated_data['date_naissance'].strip()
            if athlete.date_naissance != new_date:
                try:
                    athlete.date_naissance = new_date
                    athlete.junior_horizon = cls._calculate_junior_year(new_date)
                except ValueError as e:
                    return {"status": "ERROR_VALIDATION", "message": str(e)}

        # Fusion sécurisée du bloc UCI
        if 'uci_id_data' in updated_data and isinstance(updated_data['uci_id_data'], dict):
            current_uci = dict(athlete.uci_id_data) if athlete.uci_id_data else {}
            current_uci.update(updated_data['uci_id_data'])
            athlete.uci_id_data = current_uci

        # Fusion du bloc performance (merge profond qui conserve tous les champs, y compris poids)
        if 'donnees_performance' in updated_data and isinstance(updated_data['donnees_performance'], dict):
            current_perf = dict(athlete.donnees_performance) if athlete.donnees_performance else {}
            incoming_perf = updated_data['donnees_performance']

            # Fusion profonde pour profil_puissance (sous-dictionnaire)
            if 'profil_puissance' in incoming_perf:
                if 'profil_puissance' not in current_perf:
                    current_perf['profil_puissance'] = {}
                current_perf['profil_puissance'].update(incoming_perf.pop('profil_puissance'))

            # Tout le reste (poids, profil_manuel, metrics_*, derniers_fichiers_fit, etc.)
            current_perf.update(incoming_perf)

            athlete.donnees_performance = current_perf

        try:
            db.commit()
            print(f"🔄 [FACTORY] Fiche {athlete_id} mise à jour et synchronisée.")
            return {
                "status":     "SUCCESS",
                "athlete_id": athlete_id,
                "horizon":    athlete.junior_horizon,
                "message":    "Fiche mise à jour avec succès."
            }
        except Exception as e:
            db.rollback()
            return {"status": "ERROR_DATABASE", "message": f"Échec de l'écriture de l'update : {str(e)}"}

    # ------------------------------------------------------------------
    # ÉTAPE 3 — AVATAR
    # ------------------------------------------------------------------

    @classmethod
    def attach_avatar(cls, db: Session, athlete_id: str, source_png_path) -> dict:
        """
        AVATAR — Branche le PNG produit par avatar_chatbot_v2 sur la fiche athlète.

        PIPELINE :
            avatar_chatbot_v2 → generate_avatar() → source_png_path (Path)
                    ↓
            FicheFactory.attach_avatar()
                    ↓
            Copie vers : profiles/<athlete_id>/images/avatar.png
            Copie vers : static/profiles/<athlete_id>/images/avatar.png (pour Flask)
                    ↓
            BDD : photo_status = "AVATAR"

        Paramètres :
            db               → Session SQLAlchemy active
            athlete_id       → ID technique de l'athlète cible
            source_png_path  → Path absolu du PNG généré par le chatbot
                               (ex: ~/fjc/data/avatar/users/<user_id>/outputs/avatar_<ts>.png)

        Retourne :
            status SUCCESS      → avatar_path (Path destination), message
            status NOT_FOUND    → athlète introuvable en BDD
            status ERROR_FILE   → source PNG absente ou illisible
            status ERROR_COPY   → échec de la copie vers le coffre-fort
            status ERROR_DATABASE → échec du commit BDD
        """
        # 1. Vérification de l'athlète en BDD
        athlete = db.query(Athlete).filter(Athlete.id == athlete_id).first()
        if not athlete:
            return {"status": "NOT_FOUND", "message": f"Athlète {athlete_id} introuvable."}

        # 2. Vérification de la source
        source_path = Path(source_png_path)
        if not source_path.exists():
            return {
                "status":  "ERROR_FILE",
                "message": f"PNG source introuvable : {source_path}"
            }

        # 3. Destination dans le coffre-fort de l'athlète
        dest_dir  = PROFILES_DIR / athlete_id / "images"
        dest_path = dest_dir / "avatar.png"

        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, dest_path)
            print(f"📁 [FACTORY] Avatar copié → {dest_path}")
        except Exception as e:
            return {
                "status":  "ERROR_COPY",
                "message": f"Échec de copie vers le coffre-fort : {e}"
            }

        # 3b. Copie vers le dossier statique pour servir via Flask
        static_img_dir  = STATIC_DIR / "profiles" / athlete_id / "images"
        static_img_path = static_img_dir / "avatar.png"
        try:
            static_img_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dest_path, static_img_path)
            print(f"🌐 [FACTORY] Avatar copié vers statique → {static_img_path}")
        except Exception as e:
            print(f"⚠️  [FACTORY] Impossible de copier l'avatar en statique : {e}")
            # On ne bloque pas le processus pour un échec de copie statique

        # 4. Mise à jour BDD
        try:
            athlete.photo_status = "AVATAR"
            db.commit()
            print(f"✅ [FACTORY] Avatar attaché à la fiche {athlete_id}.")
            return {
                "status":      "SUCCESS",
                "athlete_id":  athlete_id,
                "avatar_path": str(dest_path),
                "message":     "Avatar attaché avec succès."
            }
        except Exception as e:
            db.rollback()
            return {
                "status":  "ERROR_DATABASE",
                "message": f"Échec du commit BDD : {e}"
            }


# ==============================================================================
# CRASH TEST SÉQUENTIEL (Création → Modification → Avatar)
# ==============================================================================
if __name__ == "__main__":
    from data.database import SessionLocal, engine
    from data.models import Base
    import json

    print("--- 🏭 Test d'Endurance du FicheFactory ---")
    Base.metadata.create_all(bind=engine)
    db_session = SessionLocal()

    try:
        # DONNÉES DE DÉPART
        formulaire_initial = {
            "nom":            "Gaudin",
            "prenom":         "Matthieu",
            "date_naissance": "2014-07-15",
            "sexe":           "M",
            "club":           "Vélo Club La Pomme",
            "uci_number":     "FR-12345"
        }
        user_email = "famille.gaudin@email.fr"

        print("\n1. Simulation : Création de la fiche...")
        res_creation = FicheFactory.assemble_and_store(db_session, formulaire_initial, user_email, "parent")
        print(json.dumps(res_creation, indent=2))

        target_id = res_creation.get("athlete_id")

        if target_id:
            # INTERVENTION 1 : Changement de club
            print("\n2. Simulation : Le parent modifie le club...")
            res_modif_1 = FicheFactory.update_athlete_profile(db_session, target_id, {
                "uci_id_data": {"club": "Amicale Vélo Club Aixois", "ville": "Aix-en-Provence"}
            })
            print(json.dumps(res_modif_1, indent=2))

            # INTERVENTION 2 : Injection watts depuis moteur FIT
            print("\n3. Simulation : Le moteur performance injecte des watts...")
            res_modif_2 = FicheFactory.update_athlete_profile(db_session, target_id, {
                "donnees_performance": {
                    "profil_puissance": {"5s": 450, "1min": 280}
                }
            })
            print(json.dumps(res_modif_2, indent=2))

            # INTERVENTION 3 : Avatar généré par avatar_chatbot_v2
            print("\n4. Simulation : Attachement de l'avatar généré par le chatbot...")
            # En prod, source_png_path vient de generate_avatar() :
            #   output_path, error = generate_avatar(user_id, preset)
            #   FicheFactory.attach_avatar(db, athlete_id, output_path)
            fake_avatar = BASE_DIR / f"avatar_test_{target_id}.png"
            fake_avatar.write_bytes(b"\x89PNG\r\n\x1a\n")   # header PNG minimal pour le test
            res_avatar = FicheFactory.attach_avatar(db_session, target_id, fake_avatar)
            print(json.dumps(res_avatar, indent=2))

            # VÉRIFICATION FINALE
            print("\n5. Inspection du coffre-fort final :")
            ath = db_session.query(Athlete).filter(Athlete.id == target_id).first()
            print(f"Nom/Prénom    : {ath.prenom} {ath.nom}")
            print(f"photo_status  : {ath.photo_status}")
            print(f"Club UCI      : {ath.uci_id_data}")
            print(f"Watts         : {ath.donnees_performance['profil_puissance']}")
            avatar_dest = PROFILES_DIR / target_id / "images" / "avatar.png"
            print(f"Avatar disque : {'✅ présent' if avatar_dest.exists() else '❌ absent'} ({avatar_dest})")

    finally:
        db_session.close()
