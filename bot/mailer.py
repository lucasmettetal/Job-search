"""
Module d'envoi d'email.

On utilise smtplib (inclus dans Python, pas besoin d'installer).
SMTP = Simple Mail Transfer Protocol, le protocole d'envoi d'emails.

Pour Gmail, il faut un "mot de passe d'application" :
  Mon compte Google → Sécurité → Connexion → Mots de passe des applications
  (nécessite la validation en 2 étapes activée)

Le mail est envoyé en HTML pour avoir une belle mise en page.
"""

import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import date

logger = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587  # Port TLS standard


def send_report(
    html_body: str,
    text_body: str,
    nb_offers: int,
    config: dict,
) -> bool:
    """
    Envoie le rapport d'offres par email.

    Retourne True si envoyé avec succès, False sinon.

    Paramètres :
      - html_body : version HTML du mail (belle mise en page)
      - text_body : version texte brut (fallback si HTML non supporté)
      - nb_offers : nombre d'offres (pour l'objet du mail)
      - config : le dict 'email' de config.yaml
    """
    if os.getenv("DRY_RUN", "false").lower() == "true":
        logger.info("Mode DRY_RUN : email non envoyé")
        logger.info(f"Destinataire : {config.get('recipient')}")
        return True

    sender = os.getenv("EMAIL_SENDER")
    password = os.getenv("EMAIL_APP_PASSWORD")

    if not sender or not password:
        logger.error(
            "Identifiants email manquants dans .env\n"
            "→ EMAIL_SENDER et EMAIL_APP_PASSWORD requis"
        )
        return False

    min_offers = config.get("min_offers_to_send", 1)
    if nb_offers < min_offers:
        logger.info(
            f"Seulement {nb_offers} offre(s) — "
            f"minimum requis : {min_offers}. Email non envoyé."
        )
        return False

    recipient = config.get("recipient", sender)
    subject_template = config.get(
        "subject", "[JobBot] {nb_offres} nouvelles offres - {date}"
    )
    subject = subject_template.format(
        nb_offres=nb_offers,
        date=date.today().strftime("%d/%m/%Y"),
    )

    # Créer le message MIME multipart
    # "alternative" = le client mail choisit HTML ou texte selon ses capacités
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient

    # Ajouter les deux versions (texte en premier, HTML en second)
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        logger.info(f"Envoi du mail à {recipient}...")
        # SMTP avec TLS (Transport Layer Security = connexion chiffrée)
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()          # Se présenter au serveur
            server.starttls()      # Activer le chiffrement
            server.ehlo()          # Se re-présenter après TLS
            server.login(sender, password)
            server.sendmail(sender, recipient, msg.as_string())

        logger.info(f"Email envoyé avec succès ({nb_offers} offres)")
        return True

    except smtplib.SMTPAuthenticationError:
        logger.error(
            "Erreur d'authentification Gmail.\n"
            "→ Vérifie EMAIL_APP_PASSWORD dans .env\n"
            "→ Utilise un 'mot de passe d'application', pas ton mot de passe Gmail"
        )
        return False
    except smtplib.SMTPException as e:
        logger.error(f"Erreur SMTP : {e}")
        return False
    except Exception as e:
        logger.error(f"Erreur envoi email : {e}")
        return False
