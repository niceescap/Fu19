# ~/fjc/web/webmaster.py
import sys
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

# Alignement strict pour Termux/VPS
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))

# Importation depuis la source unique de vérité
from core.config import TEMPLATES_DIR, RENDER_OUTPUT_DIR

class Webmaster:
    """
    L'Agent chargé de la construction des vues HTML.
    Il fusionne les templates avec les données backend.
    """
    def __init__(self):
        # Configuration du moteur Jinja2 pointant sur le dossier officiel
        self.env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

    def render_prototype(self, template_name: str, output_name: str, context: dict = None):
        """
        Charge un template, y injecte le dictionnaire de contexte, 
        et génère un fichier HTML physique pour visualisation locale.
        """
        if context is None:
            context = {}
            
        try:
            template = self.env.get_template(template_name)
            html_content = template.render(**context)
            
            output_path = RENDER_OUTPUT_DIR / output_name
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(html_content)
                
            print(f"✅ [WEBMASTER] Rendu réussi : {output_path.name}")
            return str(output_path)
            
        except Exception as e:
            print(f"❌ [WEBMASTER] Erreur de rendu pour {template_name} : {e}")
            return None


# ==============================================================================
# TEST DU WEBMASTER EN LOCAL (Démarrage du Serveur & Build)
# ==============================================================================
if __name__ == "__main__":
    import http.server
    import socketserver
    import os

    print("--- 🌐 Démarrage de l'Agent Webmaster ---")
    builder = Webmaster()
    
    # 1. FAUSSES DONNÉES DE CONTEXTE POUR LE PROTOTYPE
    fake_athletes = [
        {
            "id": "fjc_ath_260519_gaud_4f9b",
            "nom": "GAUDIN",
            "prenom": "Matthieu",
            "date_naissance": "2014-07-15",
            "sexe": "M",
            "junior_horizon": 2031,
            "uci_id_data": {"club": "Amicale Vélo Club Aixois", "federation": "FFC", "number": "FR-12345", "ville": "Aix-en-Provence"},
            "donnees_performance": {"profil_puissance": {"5s": 450, "1min": 280, "5min": 180, "20min": 0}}
        },
        {
            "id": "fjc_ath_260519_gaud_88za",
            "nom": "GAUDIN",
            "prenom": "Hugo",
            "date_naissance": "2016-03-22",
            "sexe": "M",
            "junior_horizon": 2033,
            "uci_id_data": {"club": "Amicale Vélo Club Aixois", "federation": "FFC", "number": "FR-99999", "ville": "Aix-en-Provence"},
            "donnees_performance": {"profil_puissance": {"5s": 320, "1min": 190, "5min": 120, "20min": 95}}
        }
    ]

    # 2. COMPILATION DE LA VUE LISTE (Nouvelle nomenclature)
    print("\nCompilation de la liste des fiches...")
    builder.render_prototype(
        template_name="fiches_list.html",
        output_name="prototype_fiches_list.html",
        context={"athletes": fake_athletes, "current_user_email": "jean.gaudin@email.com"}
    )
    
    # 3. COMPILATION DES FICHES DÉTAILLÉES INDIVIDUELLES (Nouvelle nomenclature)
    for ath in fake_athletes:
        print(f"Compilation de la fiche de {ath['prenom']}...")
        builder.render_prototype(
            template_name="fiche_athlete.html",
            output_name=f"prototype_fiche_{ath['id']}.html",
            context={"athlete": ath}
        )

    print("\n🚀 [WEBMASTER] Tous les gabarits sont assemblés.")
    
    # 4. LANCEMENT DU SERVEUR LOCAL (Sera exécuté si lancé sans l'alias complet, par sécurité)
    PORT = 8000
    os.chdir(RENDER_OUTPUT_DIR)
    Handler = http.server.SimpleHTTPRequestHandler
    
    class MyTCPServer(socketserver.TCPServer):
        allow_reuse_address = True

    print(f"\n🌐 [SERVEUR LOCAL] Lancement du serveur de test...")
    print(f"🔗 Adresse liste : http://127.0.0.1:{PORT}/prototype_fiches_list.html")
    print("💡 Pour couper le serveur : Faites CTRL+C\n")
    
    try:
        with MyTCPServer(("", PORT), Handler) as httpd:
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 Serveur local arrêté proprement.")
