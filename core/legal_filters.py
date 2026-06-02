# ~/fjc/core/legal_filters.py

def validate_legal_requirements(form_data: dict):
    """
    Filtre légal strict (RGPD & Protection des mineurs).
    Vérifie le consentement explicite du parent ou l'attestation du coach.
    """
    # 1. Vérification de la case cochée (engagement légal)
    # Dans un formulaire, une checkbox renvoie généralement True, 'true', ou 'on'
    consentement = form_data.get('parental_consent')
    
    if consentement not in [True, 'true', 'on', 'True']:
        return False, "Le consentement ou l'attestation sur l'honneur est obligatoire pour inscrire un mineur."

    # 2. Vérification de la signature numérique (Nom du déclarant)
    declarant_name = form_data.get('parent_full_name', '').strip()
    if len(declarant_name) < 4:
        return False, "La signature numérique (Nom complet du déclarant) est obligatoire ou trop courte."

    # 3. Validation du rôle pour traçabilité juridique
    role = form_data.get('user_role', 'collaborator')
    if role not in ['parent', 'coach', 'creator', 'agent']:
        return False, "Le rôle du déclarant est invalide pour l'établissement des droits de diffusion."

    # Message de succès adapté au profil
    if role == 'coach':
        msg = f"Validation légale acceptée. L'éducateur ({declarant_name}) atteste détenir l'autorisation parentale."
    else:
        msg = f"Validation légale acceptée. Le représentant légal ({declarant_name}) a signé le consentement."

    return True, msg
