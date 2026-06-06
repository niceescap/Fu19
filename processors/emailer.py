# /processors/emailer.py
"""
EMAILER — Moteur d'envoi SMTP isolé
FJC / fU19 Platform

Responsabilité unique : envoyer le magic link d'authentification.
Appelé par app.py via send_magic_link(), jamais directement par l'utilisateur.

Configuration attendue dans .env :
    FU19_SMTP_USER=auth@fu19.org
    FU19_SMTP_KEY=votre_clé_tem
    BASE_URL=https://fu19.org
"""

import os
import sys
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# ==============================================================================
# CONFIGURATION SMTP — lecture .env via core.config
# ==============================================================================

SMTP_HOST   = "smtp.tem.scaleway.com"
SMTP_PORT   = 465                                        # TLS natif (SSL)
SMTP_USER   = os.environ.get("FU19_SMTP_USER", "")      # auth@fu19.org
SMTP_KEY    = os.environ.get("FU19_SMTP_KEY", "")
SENDER_NAME = "Next U19 Platform"
SENDER_ADDR = "auth@fu19.org"                                  # expéditeur = utilisateur SMTP

logger = logging.getLogger(__name__)


# ==============================================================================
# CONSTRUCTION DU MESSAGE
# ==============================================================================

def _build_message(to_email: str, magic_url: str) -> MIMEMultipart:
    """
    Construit le message MIME multipart (texte brut + HTML).
    Le client email choisit la meilleure version disponible.
    """
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "🔗 Votre lien de connexion — fU19 Platform"
    msg["From"]    = f"{SENDER_NAME} <{SENDER_ADDR}>"
    msg["To"]      = to_email

    # ── Version texte brut (fallback) ─────────────────────────────────
    text_content = (
        f"Bienvenue,\n\n"
        f"Cliquez sur le lien suivant pour valider votre déclaration "
        f"et vous connecter (valable 15 minutes) :\n\n"
        f"{magic_url}\n\n"
        f"Si vous n'êtes pas à l'origine de cette demande, ignorez cet e-mail.\n\n"
        f"— L'équipe fU19"
    )

    # ── Version HTML ───────────────────────────────────────────────────
    html_content = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0;padding:0;background:#f8fafc;font-family:sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0"
         style="background:#f8fafc;padding:40px 0;">
    <tr>
      <td align="center">
        <table width="560" cellpadding="0" cellspacing="0"
               style="background:#ffffff;border-radius:12px;
                      box-shadow:0 2px 8px rgba(0,0,0,0.08);
                      overflow:hidden;">

          <!-- EN-TÊTE -->
          <tr>
            <td style="background:#4f46e5;padding:28px 40px;">
              <span style="color:#ffffff;font-size:20px;font-weight:800;
                           letter-spacing:-0.5px;">
                Next U19 &nbsp;·&nbsp; Platform
              </span>
            </td>
          </tr>

          <!-- CORPS -->
          <tr>
            <td style="padding:40px 40px 32px;">
              <p style="margin:0 0 16px;font-size:16px;color:#1e293b;line-height:1.6;">
                Bonjour,
              </p>
              <p style="margin:0 0 28px;font-size:15px;color:#475569;line-height:1.7;">
                Vous venez de soumettre une demande d'inscription à la plateforme
                <strong>fU19</strong>, le tiers de confiance en ligne pour les
                résultats des jeunes champions cyclistes. Validez votre engagement
                et finalisez l'opération en cliquant sur le bouton ci-dessous :
              </p>

              <!-- BOUTON -->
              <table cellpadding="0" cellspacing="0">
                <tr>
                  <td style="border-radius:8px;background:#4f46e5;">
                    <a href="{magic_url}"
                       style="display:inline-block;padding:14px 32px;
                              color:#ffffff;font-size:15px;font-weight:700;
                              text-decoration:none;letter-spacing:0.2px;">
                      ✅ &nbsp;Valider et accéder à mon espace
                    </a>
                  </td>
                </tr>
              </table>

              <p style="margin:28px 0 0;font-size:13px;color:#94a3b8;line-height:1.6;">
                Ce lien est valable <strong>15 minutes</strong> et ne peut être
                utilisé qu'une seule fois.<br>
                Si vous n'êtes pas à l'origine de cette demande, ignorez cet e-mail.
              </p>
            </td>
          </tr>

          <!-- PIED -->
          <tr>
            <td style="padding:20px 40px;border-top:1px solid #f1f5f9;">
              <p style="margin:0;font-size:12px;color:#cbd5e1;text-align:center;">
                Next U19 Platform &nbsp;·&nbsp; fu19.org
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    msg.attach(MIMEText(text_content, "plain", "utf-8"))
    msg.attach(MIMEText(html_content, "html",  "utf-8"))
    return msg


# ==============================================================================
# POINT D'ENTRÉE PUBLIC
# ==============================================================================

def send_magic_link(to_email: str, magic_url: str) -> dict:
    """
    Envoie le magic link à l'adresse indiquée via SMTP TLS (port 465).

    Retourne :
        {"status": "SUCCESS"}
        {"status": "ERROR", "message": str}
    """
    if not SMTP_USER or not SMTP_KEY:
        msg = "Variables SMTP manquantes (FU19_SMTP_USER / FU19_SMTP_KEY)."
        logger.error(msg)
        return {"status": "ERROR", "message": msg}

    try:
        message = _build_message(to_email, magic_url)

        # Port 465 → SSL natif (SMTP_SSL), pas STARTTLS
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
            server.login(SMTP_USER, SMTP_KEY)
            server.sendmail(SENDER_ADDR, to_email, message.as_string())

        logger.info(f"[EMAILER] Magic link envoyé → {to_email}")
        return {"status": "SUCCESS"}

    except smtplib.SMTPAuthenticationError:
        msg = "Échec d'authentification SMTP. Vérifiez FU19_SMTP_USER et FU19_SMTP_KEY."
        logger.error(f"[EMAILER] {msg}")
        return {"status": "ERROR", "message": msg}

    except smtplib.SMTPException as e:
        msg = f"Erreur SMTP : {str(e)}"
        logger.error(f"[EMAILER] {msg}")
        return {"status": "ERROR", "message": msg}

    except Exception as e:
        msg = f"Erreur inattendue : {str(e)}"
        logger.error(f"[EMAILER] {msg}")
        return {"status": "ERROR", "message": msg}

