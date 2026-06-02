# ~/fjc/auth/onboarding.py
import datetime
import sys
from pathlib import Path

# Alignement des chemins pour l'exécution dans n'importe quel environnement (Termux/VPS)
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))

from core.config import PROFILES_DIR
from core.legal_filters import validate_legal_requirements
from data.models import Athlete
from data.queries import create_athlete_with_owner
from sqlalchemy.orm import Session


def calculate_junior_year(birth_date_str):
    """
    Calcule l'année théorique d'accession à la catégorie Junior UCI.
    Règle immuable : l'année des 17 ans de l'athlète.
    """
    try:
        birth_year = int(birth_date_str.split('-')[0])
        return birth_year + 17
    except (ValueError, AttributeError, IndexError):
        raise ValueError("Format de date invalide. Attendu : YYYY-MM-DD.")

def process_athlete_onboarding(db: Session, form_data: dict, owner_email: str):
    """
    Agent principal d'onboarding : filtre, valide, structure 
    et coordonne l'écriture de la fiche athlète.
    """
    
    # 1. TAMIS LÉGAL : Validation du consentement ou de l'autorisation
    is_legal, legal_msg = validate_legal_requirements(form_data)
    if not is_legal:
        return {"status": "ERROR_LEGAL", "message": legal_msg}

    # Nettoyage et normalisation des données textuelles de base
    nom = form_data.get('nom', '').strip().upper()
    prenom = form_data.get('prenom', '').strip().capitalize()
    date_naissance = form_data.get('date_naissance', '').strip()
    sexe = form_data.get('sexe', '').strip().upper()

    if not nom or not prenom or not date_naissance or sexe not in ['M', 'F']:
        return {"status": "ERROR_VALIDATION", "message": "Champs obligatoires manquants ou invalides (Nom, Prénom, Date de naissance, Sexe)."}

    # 2. TAMIS ANTI-DOUBLONS : Vérification d'existence en base
    existing_athlete = db.query(Athlete).filter(
        Athlete.nom == nom,
        Athlete.prenom == prenom,
        Athlete.date_naissance == date_naissance
    ).first()

    if existing_athlete:
        return {
            "status": "DUPLICATE_FOUND",
            "message": f"Un athlète nommé {prenom} {nom}, né le {date_naissance}, est déjà enregistré sur la plateforme.",
            "athlete_id": existing_athlete.id
        }

    # 3. CALCULS AUTOMATIQUES : Horizon Junior
    try:
        junior_horizon = calculate_junior_year(date_naissance)
    except ValueError as e:
        return {"status": "ERROR_VALIDATION", "message": str(e)}

    # 4. GÉNÉRATION DE L'IDENTIFIANT TECHNIQUE UNIQUE
    timestamp = datetime.datetime.now().strftime('%y%m%d')
    nom_clean = nom.replace(' ', '').lower()[:4]
    athlete_id = f"fjc_ath_{timestamp}_{nom_clean}"

    # 5. STRUCTURATION DES SUBDIVISIONS HYBRIDES (Données minimales de départ / Cold Start)
    uci_id_data = {
        "number": form_data.get('uci_number', '').replace(' ', ''),
        "status": "UNVERIFIED",
        "federation": form_data.get('federation', 'Inconnue'),
        "club": form_data.get('club', 'Indépendant'),
        "ville": form_data.get('ville', '-')
    }

    medias = {
        "links": form_data.get('social_links', {}),
        "galerie": []
    }

    athlete_record = {
        "id": athlete_id,
        "nom": nom,
        "prenom": prenom,
        "date_naissance": date_naissance,
        "sexe": sexe,
        "junior_horizon": junior_horizon,
        "nationalite": form_data.get('nationalite', 'FR').upper()[:2],
        "photo_status": "PENDING",  # Bloqué par défaut en attente de modération vision
        "uci_id_data": uci_id_data,
        "palmares": [],
        "donnees_performance": {
            "derniers_fichiers_fit": [],
            "profil_puissance": {},
            "metriques_max": {}
        },
        "medias": medias,
        "partenaires": []
    }

    # 6. CRÉATION DU DOSSIER PHYSIQUE (Stockage local asynchrone des médias/.FIT)
    athlete_dir = PROFILES_DIR / athlete_id
    try:
        athlete_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return {"status": "ERROR_SYSTEM", "message": f"Erreur critique lors du provisionnement du stockage : {str(e)}"}

    # 7. INJECTION TRANSACTIONNELLE EN BASE DE DONNÉES
    try:
        role_declared = form_data.get('user_role', 'collaborator')  # creator, coach, parent, agent
        create_athlete_with_owner(
            db=db, 
            athlete_record=athlete_record, 
            owner_email=owner_email, 
            role=role_declared
        )
        return {
            "status": "SUCCESS",
            "athlete_id": athlete_id,
            "horizon": junior_horizon,
            "message": f"Fiche de {prenom} {nom} créée avec succès et rattachée à {owner_email}."
        }
    except Exception as e:
        return {"status": "ERROR_DATABASE", "message": f"Échec de l'écriture en base de données : {str(e)}"}


# ==============================================================================
# SCRIPT DE TEST INTEGRÉ DANS L'ENVIRONNEMENT LOCAL (Termux)
# ==============================================================================
if __name__ == "__main__":
    from data.database import SessionLocal, engine
    from data.models import Base
    import json

    print("--- 🛠️ Lancement du test réel de l'Agent Onboarding ---")
    
    # S'assurer que les tables SQLite locales existent
    Base.metadata.create_all(bind=engine)
    
    # Ouverture d'une session de base de données de test
    db_session = SessionLocal()
    
    try:
        # Données fictives simulant l'envoi d'un formulaire par un coach d'école de vélo
        formulaire_test = {
            "nom": "Gaudin",
            "prenom": "Hugo",
            "date_naissance": "2013-08-22",
            "sexe": "M",
            "nationalite": "FR",
            "uci_number": "101 234 567 89",
            "federation": "FFC",
            "club": "Amicale Vélo Club Aixois",
            "ville": "Aix-en-Provence",
            "parental_consent": True,          # Passe le filtre légal
            "parent_full_name": "Jean Gaudin", # Signature légale
            "user_role": "coach"               # Rôle de liaison
        }
        
        email_manager = "coach.aix@avca.fr"
        
        print(f"1. Tentative d'onboarding pour : {formulaire_test['prenom']} {formulaire_test['nom']}...")
        result = process_athlete_onboarding(db_session, formulaire_test, email_manager)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        
        print("\n2. Test de sécurité : Tentative d'insertion du même profil (Détection doublon)...")
        duplicate_result = process_athlete_onboarding(db_session, formulaire_test, email_manager)
        print(json.dumps(duplicate_result, indent=2, ensure_ascii=False))

    finally:
        db_session.close()
