# ~/fjc/processors/notifier.py
"""
NOTIFIER — Emails transactionnels FJC
Distinct de emailer.py (magic link auth) — ce module gère les notifications
liées au cycle de vie des fiches : revendication et signalement.

Fonctions exposées :
    send_claim_magic_link()      → Email au demandeur de revendication
    send_report_notification()   → Email aux admins pour signalement
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

from core.config import ADMIN_EMAILS

# ==============================================================================
# CONFIGURATION SMTP — identique à emailer.py
# ==============================================================================

SMTP_HOST   = "smtp.tem.scaleway.com"
SMTP_PORT   = 465
SMTP_USER   = os.environ.get("FU19_SMTP_USER", "")
SMTP_KEY    = os.environ.get("FU19_SMTP_KEY", "")
SENDER_NAME = "Next U19 Platform"
SENDER_ADDR = "auth@fu19.org"
BASE_URL    = os.environ.get("BASE_URL", "https://fu19.org")

logger = logging.getLogger(__name__)


# ==============================================================================
# UTILITAIRE SMTP INTERNE
# ==============================================================================

def _send(to_email: str, message: MIMEMultipart) -> dict:
    """Envoi SMTP SSL mutualisé. Retourne {"status": "SUCCESS"} ou {"status": "ERROR", ...}"""
    if not SMTP_USER or not SMTP_KEY:
        msg = "Variables SMTP manquantes (FU19_SMTP_USER / FU19_SMTP_KEY)."
        logger.error(msg)
        return {"status": "ERROR", "message": msg}
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
            server.login(SMTP_USER, SMTP_KEY)
            server.sendmail(SENDER_ADDR, to_email, message.as_string())
        logger.info(f"[NOTIFIER] Email envoyé → {to_email}")
        return {"status": "SUCCESS"}
    except smtplib.SMTPAuthenticationError:
        msg = "Échec d'authentification SMTP."
        logger.error(f"[NOTIFIER] {msg}")
        return {"status": "ERROR", "message": msg}
    except smtplib.SMTPException as e:
        msg = f"Erreur SMTP : {str(e)}"
        logger.error(f"[NOTIFIER] {msg}")
        return {"status": "ERROR", "message": msg}
    except Exception as e:
        msg = f"Erreur inattendue : {str(e)}"
        logger.error(f"[NOTIFIER] {msg}")
        return {"status": "ERROR", "message": msg}


# ==============================================================================
# 1. REVENDICATION — Magic link vers le demandeur
# ==============================================================================

def send_claim_magic_link(to_email: str, athlete_name: str, magic_url: str) -> dict:
    """
    Envoie le lien de revendication au demandeur.
    Appelé après validation de legal_filters dans la route POST /fiche/<id>/revendiquer.

    Paramètres :
        to_email      → adresse du demandeur
        athlete_name  → "Prénom NOM" pour personnaliser l'email
        magic_url     → URL /auth/claim?token=...&email=...&athlete_id=...
    """
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🔗 Revendication de la fiche — {athlete_name}"
    msg["From"]    = f"{SENDER_NAME} <{SENDER_ADDR}>"
    msg["To"]      = to_email

    text = (
        f"Bonjour,\n\n"
        f"Vous avez demandé à revendiquer la fiche de {athlete_name} "
        f"sur la plateforme fU19.\n\n"
        f"Cliquez sur le lien ci-dessous pour valider votre engagement légal "
        f"et rattacher cette fiche à votre compte (valable 15 minutes) :\n\n"
        f"{magic_url}\n\n"
        f"Si vous n'êtes pas à l'origine de cette demande, ignorez cet e-mail.\n\n"
        f"— L'équipe fU19"
    )

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f8fafc;font-family:sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f8fafc;padding:40px 0;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0"
             style="background:#fff;border-radius:12px;box-shadow:0 2px 8px rgba(0,0,0,0.08);overflow:hidden;">

        <tr>
          <td style="background:#4f46e5;padding:28px 40px;">
            <span style="color:#fff;font-size:20px;font-weight:800;letter-spacing:-0.5px;">
              Next U19 &nbsp;·&nbsp; Platform
            </span>
          </td>
        </tr>

        <tr>
          <td style="padding:40px 40px 32px;">
            <p style="margin:0 0 16px;font-size:16px;color:#1e293b;line-height:1.6;">Bonjour,</p>
            <p style="margin:0 0 12px;font-size:15px;color:#475569;line-height:1.7;">
              Vous avez demandé à revendiquer la fiche de
              <strong>{athlete_name}</strong> sur la plateforme <strong>fU19</strong>,
              le tiers de confiance en ligne pour les résultats des jeunes champions cyclistes.
            </p>
            <p style="margin:0 0 28px;font-size:15px;color:#475569;line-height:1.7;">
              En cliquant sur le bouton ci-dessous, vous confirmez détenir l'autorisation
              parentale ou la qualité de représentant légal pour gérer cette fiche.
            </p>

            <table cellpadding="0" cellspacing="0">
              <tr>
                <td style="border-radius:8px;background:#4f46e5;">
                  <a href="{magic_url}"
                     style="display:inline-block;padding:14px 32px;color:#fff;
                            font-size:15px;font-weight:700;text-decoration:none;">
                    ✅ &nbsp;Valider et revendiquer la fiche
                  </a>
                </td>
              </tr>
            </table>

            <p style="margin:28px 0 0;font-size:13px;color:#94a3b8;line-height:1.6;">
              Ce lien est valable <strong>15 minutes</strong> et ne peut être utilisé qu'une seule fois.<br>
              Si vous n'êtes pas à l'origine de cette demande, ignorez cet e-mail.
            </p>
          </td>
        </tr>

        <tr>
          <td style="padding:20px 40px;border-top:1px solid #f1f5f9;">
            <p style="margin:0;font-size:12px;color:#cbd5e1;text-align:center;">
              Next U19 Platform &nbsp;·&nbsp; fu19.org
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""

    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html,  "html",  "utf-8"))
    return _send(to_email, msg)


# ==============================================================================
# 2. SIGNALEMENT — Notification vers tous les ADMIN_EMAILS
# ==============================================================================

REPORT_REASONS = {
    "inexact":      "Informations inexactes ou erronées",
    "usurpation":   "Usurpation d'identité ou fiche non autorisée",
    "mineur":       "Protection du mineur — contenu inapproprié",
    "doublon":      "Fiche en doublon",
    "autre":        "Autre motif",
}

def send_report_notification(
    athlete_id: str,
    athlete_name: str,
    reason_key: str,
    detail: str,
    reporter_email: str
) -> dict:
    """
    Envoie une notification de signalement à tous les ADMIN_EMAILS.
    Appelé après validation du magic link du reporter (/auth/report).

    Paramètres :
        athlete_id      → ID technique de la fiche signalée
        athlete_name    → "Prénom NOM"
        reason_key      → clé parmi REPORT_REASONS
        detail          → texte libre optionnel du reporter
        reporter_email  → adresse du reporter (vérifiée par magic link)
    """
    if not ADMIN_EMAILS:
        msg = "Aucun ADMIN_EMAILS configuré — signalement non transmis."
        logger.error(f"[NOTIFIER] {msg}")
        return {"status": "ERROR", "message": msg}

    reason_label = REPORT_REASONS.get(reason_key, reason_key)
    fiche_url    = f"{BASE_URL}/fiche/{athlete_id}"

    results = []
    for admin_email in ADMIN_EMAILS:

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"⚠️ Signalement fiche — {athlete_name}"
        msg["From"]    = f"{SENDER_NAME} <{SENDER_ADDR}>"
        msg["To"]      = admin_email

        text = (
            f"Signalement reçu sur fU19\n\n"
            f"Fiche concernée : {athlete_name}\n"
            f"ID              : {athlete_id}\n"
            f"URL             : {fiche_url}\n\n"
            f"Motif           : {reason_label}\n"
            f"Détail          : {detail or 'Aucun détail fourni'}\n\n"
            f"Reporter        : {reporter_email}\n\n"
            f"— Système automatique fU19"
        )

        html = f"""<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f8fafc;font-family:sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f8fafc;padding:40px 0;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0"
             style="background:#fff;border-radius:12px;box-shadow:0 2px 8px rgba(0,0,0,0.08);overflow:hidden;">

        <tr>
          <td style="background:#dc2626;padding:28px 40px;">
            <span style="color:#fff;font-size:20px;font-weight:800;letter-spacing:-0.5px;">
              ⚠️ &nbsp;Signalement — fU19 Platform
            </span>
          </td>
        </tr>

        <tr>
          <td style="padding:40px 40px 32px;">
            <p style="margin:0 0 24px;font-size:15px;color:#475569;line-height:1.7;">
              Un signalement a été soumis et vérifié sur la plateforme fU19.
            </p>

            <table width="100%" cellpadding="0" cellspacing="0"
                   style="background:#f8fafc;border-radius:8px;border:1px solid #e2e8f0;
                          margin-bottom:24px;">
              <tr>
                <td style="padding:20px 24px;">
                  <table width="100%" cellpadding="4" cellspacing="0">
                    <tr>
                      <td style="font-size:12px;font-weight:700;color:#94a3b8;
                                 text-transform:uppercase;letter-spacing:1px;width:120px;">
                        Fiche
                      </td>
                      <td style="font-size:14px;font-weight:700;color:#0f172a;">
                        {athlete_name}
                      </td>
                    </tr>
                    <tr>
                      <td style="font-size:12px;font-weight:700;color:#94a3b8;
                                 text-transform:uppercase;letter-spacing:1px;">
                        ID
                      </td>
                      <td style="font-size:13px;color:#475569;font-family:monospace;">
                        {athlete_id}
                      </td>
                    </tr>
                    <tr>
                      <td style="font-size:12px;font-weight:700;color:#94a3b8;
                                 text-transform:uppercase;letter-spacing:1px;">
                        Motif
                      </td>
                      <td style="font-size:14px;font-weight:700;color:#dc2626;">
                        {reason_label}
                      </td>
                    </tr>
                    <tr>
                      <td style="font-size:12px;font-weight:700;color:#94a3b8;
                                 text-transform:uppercase;letter-spacing:1px;">
                        Détail
                      </td>
                      <td style="font-size:14px;color:#475569;">
                        {detail or '<em>Aucun détail fourni</em>'}
                      </td>
                    </tr>
                    <tr>
                      <td style="font-size:12px;font-weight:700;color:#94a3b8;
                                 text-transform:uppercase;letter-spacing:1px;">
                        Reporter
                      </td>
                      <td style="font-size:14px;color:#475569;">
                        {reporter_email}
                      </td>
                    </tr>
                  </table>
                </td>
              </tr>
            </table>

            <table cellpadding="0" cellspacing="0">
              <tr>
                <td style="border-radius:8px;background:#0f172a;">
                  <a href="{fiche_url}"
                     style="display:inline-block;padding:12px 28px;color:#fff;
                            font-size:14px;font-weight:700;text-decoration:none;">
                    👁 Consulter la fiche signalée
                  </a>
                </td>
              </tr>
            </table>

            <p style="margin:24px 0 0;font-size:13px;color:#94a3b8;line-height:1.6;">
              La fiche n'a pas été modifiée automatiquement.<br>
              Un suivi humain est attendu de votre part.
            </p>
          </td>
        </tr>

        <tr>
          <td style="padding:20px 40px;border-top:1px solid #f1f5f9;">
            <p style="margin:0;font-size:12px;color:#cbd5e1;text-align:center;">
              Next U19 Platform &nbsp;·&nbsp; fu19.org &nbsp;·&nbsp; Système automatique
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""

        msg.attach(MIMEText(text, "plain", "utf-8"))
        msg.attach(MIMEText(html,  "html",  "utf-8"))
        results.append(_send(admin_email, msg))

    errors = [r for r in results if r["status"] == "ERROR"]
    if not errors:
        return {"status": "SUCCESS"}
    if len(errors) == len(results):
        return {"status": "ERROR", "message": "Échec d'envoi vers tous les admins."}
    return {"status": "PARTIAL", "message": f"{len(errors)} admin(s) non notifié(s)."}
