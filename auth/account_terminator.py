# Logique conceptuelle de auth/account_terminator.py

def delete_user_account(db_session, user_email):
    """
    Supprime un compte utilisateur et gère les fiches athlètes associées.
    """
    user = db_session.query(User).filter(User.email == user_email).first()
    
    # Parcourir tous les athlètes gérés par cet utilisateur
    for athlete in user.athletes:
        # Compter combien d'owners possède cet athlète au total
        total_owners = len(athlete.owners)
        
        if total_owners == 1:
            # S'il était le SEUL et UNIQUE gestionnaire de la fiche
            # 1. On bloque la diffusion publique immédiatement
            athlete.status = "ARCHIVED"
            
            # 2. Déclenchement du message d'avertissement spécifique
            send_warning_archive_notification(
                email=user_email,
                athlete_name=f"{athlete.prenom} {athlete.nom}",
                message=(
                    "Attention : Vous êtes le dernier gestionnaire de cet athlète. "
                    "En supprimant votre compte, sa fiche ne sera plus publiée. "
                    "Ses données de performance (.FIT) et son palmarès sont "
                    "sécurisés et archivés dans notre coffre-fort numérique."
                )
            )
        else:
            # S'il reste d'autres owners (ex: l'autre parent ou le club)
            # La fiche reste PUBLIC, on retire juste cet utilisateur de la liste
            send_standard_withdrawal_notification(athlete.owners)

    # Suppression effective de la ligne de l'utilisateur dans la table 'users'
    # Grâce au Many-to-Many, la liaison dans 'athlete_owners' saute, 
    # mais la ligne dans la table 'athletes' reste intacte en mode "ARCHIVED".
    db_session.delete(user)
    db_session.commit()
