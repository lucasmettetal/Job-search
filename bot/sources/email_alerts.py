"""
Source : Alertes email emploi (LinkedIn, Indeed, HelloWork, WTTJ, APEC...)

PRINCIPE :
  Les grands sites d'emploi proposent des "alertes email" gratuites.
  Tu configures une alerte (mots-clés + lieu) sur chaque site,
  ils t'envoient des emails quand de nouvelles offres apparaissent.
  Ce module lit ces emails via IMAP et en extrait les offres.

  → 100% légal, pas de scraping, aucun risque de blocage.

CONFIGURATION REQUISE :
  Dans .env :
    IMAP_EMAIL=ton.email@gmail.com
    IMAP_PASSWORD=mot_de_passe_application_gmail
    IMAP_HOST=imap.gmail.com            # auto-détecté si Gmail/Outlook
    IMAP_PORT=993                       # IMAPS (SSL), standard

  Pour Gmail : utilise un "mot de passe d'application" (pas ton vrai mdp).
    → Compte Google → Sécurité → Mots de passe des applications

SITES À CONFIGURER (crée des alertes sur chacun) :
  LinkedIn   : linkedin.com/jobs → "Alertes emploi"
  Indeed     : fr.indeed.com → "Créer une alerte emploi"
  HelloWork  : hellowork.com → "Créer une alerte"
  WTTJ       : welcometothejungle.com → "Mes alertes"
  APEC       : apec.fr → "Créer une alerte offre"
  Monster    : monster.fr → "Alertes emploi"

COMMENT FONCTIONNE LE PARSING :
  Chaque service envoie des emails HTML avec ses propres structures.
  On utilise BeautifulSoup pour parser le HTML des emails.
  Pour LinkedIn et Indeed, on a des parsers dédiés.
  Pour les autres, un parser générique extrait les liens d'offres.
"""

import email
import hashlib
import imaplib
import logging
import os
import re
import time
from email.header import decode_header as _decode_header
from typing import Optional

from bot.models import JobOffer
from bot.sources.base import JobSource

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False
    BeautifulSoup = None  # type: ignore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration des expéditeurs connus
# Format : fragment de domaine → (nom lisible, méthode de parsing)
# ---------------------------------------------------------------------------
SENDER_MAP: dict[str, tuple[str, str]] = {
    "linkedin.com":            ("LinkedIn",   "_parse_linkedin"),
    "indeed.com":              ("Indeed",     "_parse_indeed"),
    "hellowork.com":           ("HelloWork",  "_parse_generic"),
    "welcometothejungle.com":  ("WTTJ",       "_parse_generic"),
    "apec.fr":                 ("APEC",       "_parse_generic"),
    "monster.fr":              ("Monster",    "_parse_generic"),
    "cadremploi.fr":           ("Cadremploi", "_parse_generic"),
    "regionsjob.com":          ("RegionsJob", "_parse_generic"),
    "pole-emploi.fr":          ("FranceTravail", "_parse_generic"),
    "francetravail.fr":        ("FranceTravail", "_parse_generic"),
}

# IMAP auto-détecté selon le domaine email
IMAP_AUTO: dict[str, tuple[str, int]] = {
    "gmail.com":     ("imap.gmail.com",              993),
    "googlemail.com":("imap.gmail.com",              993),
    "outlook.com":   ("imap-mail.outlook.com",       993),
    "hotmail.com":   ("imap-mail.outlook.com",       993),
    "live.com":      ("imap-mail.outlook.com",       993),
    "yahoo.fr":      ("imap.mail.yahoo.com",         993),
    "yahoo.com":     ("imap.mail.yahoo.com",         993),
    "laposte.net":   ("imap.laposte.net",            993),
    "orange.fr":     ("imap.orange.fr",              993),
    "free.fr":       ("imap.free.fr",                993),
    "sfr.fr":        ("imap.sfr.fr",                 993),
    "wanadoo.fr":    ("imap.orange.fr",              993),
}

# Patterns dans les URLs qui indiquent un lien vers une offre d'emploi
JOB_URL_PATTERNS = [
    r"linkedin\.com/jobs/view/",
    r"indeed\.com/rc/clk",
    r"indeed\.com/viewjob",
    r"hellowork\.com/.+/offre",
    r"welcometothejungle\.com/.+/jobs/",
    r"apec\.fr/offre",
    r"monster\..+/job/",
    r"cadremploi\.fr/offre",
    r"regionsjob\.com/offre",
    r"/offre[-_s]?[-/]emploi",
    r"job[-_s]?detail",
    r"offres?[-/]\d+",
]

JOB_URL_RE = re.compile(
    "|".join(JOB_URL_PATTERNS), re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Classe principale
# ---------------------------------------------------------------------------

class EmailAlertsSource(JobSource):
    """
    Lit les alertes email d'emploi reçues dans ta boîte mail
    et en extrait les offres d'emploi.
    """

    name = "email_alerts"

    def __init__(self, config: dict):
        super().__init__(config)

        self.imap_email = os.getenv("IMAP_EMAIL", "")
        self.imap_password = os.getenv("IMAP_PASSWORD", "")

        # Auto-détection du serveur IMAP selon le domaine
        email_domain = self.imap_email.split("@")[-1].lower()
        auto_host, auto_port = IMAP_AUTO.get(
            email_domain, ("", 993)
        )
        self.imap_host = os.getenv("IMAP_HOST", auto_host)
        self.imap_port = int(os.getenv("IMAP_PORT", auto_port or 993))

        # Depuis combien de jours chercher les emails ?
        self.days_back = self.source_config.get("days_back", 2)

        # Marquer les emails lus après traitement ?
        self.mark_as_read = self.source_config.get(
            "mark_as_read", False
        )

        # Dossier IMAP à surveiller (INBOX par défaut)
        self.mailbox = self.source_config.get("mailbox", "INBOX")

    def is_available(self) -> bool:
        if not HAS_BS4:
            logger.warning(
                "EmailAlerts : beautifulsoup4 non installé. "
                "Lance : pip install beautifulsoup4"
            )
            return False
        if not self.imap_email or not self.imap_password:
            return False
        if not self.imap_host:
            logger.warning(
                f"EmailAlerts : domaine '{self.imap_email.split('@')[-1]}' "
                f"non reconnu. Renseigne IMAP_HOST dans .env"
            )
            return False
        return True

    # ------------------------------------------------------------------
    # Connexion IMAP
    # ------------------------------------------------------------------

    def _connect(self) -> imaplib.IMAP4_SSL:
        """
        Ouvre une connexion IMAP sécurisée (SSL sur port 993).

        IMAP = Internet Message Access Protocol.
        C'est le protocole qui permet de lire les emails depuis un client.
        Gmail, Outlook, etc. supportent tous IMAP.
        """
        logger.info(
            f"Connexion IMAP à {self.imap_host}:{self.imap_port}"
        )
        mail = imaplib.IMAP4_SSL(self.imap_host, self.imap_port)
        mail.login(self.imap_email, self.imap_password)
        logger.info("Connexion IMAP établie")
        return mail

    def _fetch_alert_emails(
        self, mail: imaplib.IMAP4_SSL
    ) -> list[tuple[str, str, str]]:
        """
        Cherche dans la boîte les emails d'alerte emploi récents.

        Retourne une liste de tuples : (uid, sender, html_body)

        Stratégie de recherche :
          On cherche les emails des N derniers jours (SINCE).
          On ne filtre PAS par expéditeur ici — on le fait après,
          pour éviter de rater des alertes d'un service inconnu.

        Note : IMAP utilise des dates au format "DD-Mon-YYYY"
        """
        from datetime import datetime, timedelta
        from email.utils import parsedate_to_datetime

        # Date limite : aujourd'hui - N jours
        since_date = (
            datetime.now() - timedelta(days=self.days_back)
        ).strftime("%d-%b-%Y")

        mail.select(self.mailbox)

        # Cherche les emails depuis la date limite
        # On cherche aussi les emails vus (SEEN) car certains
        # clients email marquent automatiquement comme lus
        _, data = mail.search(None, f'SINCE "{since_date}"')

        if not data or not data[0]:
            logger.info("Aucun email récent trouvé")
            return []

        uids = data[0].split()
        logger.info(
            f"{len(uids)} email(s) récent(s) à analyser"
        )

        results = []
        for uid in uids[-50:]:  # Limite à 50 pour ne pas bloquer
            try:
                _, msg_data = mail.fetch(uid, "(RFC822)")
                if not msg_data or not msg_data[0]:
                    continue

                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)

                sender = self._decode_header_value(
                    msg.get("From", "")
                )
                subject = self._decode_header_value(
                    msg.get("Subject", "")
                )

                # Vérifier si c'est bien une alerte emploi connue
                source_name = self._detect_source(sender)
                if not source_name:
                    # Vérifier le sujet pour les alertes non reconnues
                    if not self._looks_like_job_alert(subject):
                        continue

                html_body = self._get_html_body(msg)
                if not html_body:
                    continue

                logger.debug(
                    f"Email alerte trouvé : {sender[:40]} — {subject[:50]}"
                )
                results.append((uid.decode(), sender, html_body))

                # Marquer comme lu si demandé
                if self.mark_as_read:
                    mail.store(uid, "+FLAGS", "\\Seen")

            except Exception as e:
                logger.debug(f"Erreur lecture email uid={uid} : {e}")
                continue

        return results

    def _decode_header_value(self, raw: str) -> str:
        """
        Décode les en-têtes email (souvent encodés en base64 ou quoted-printable).
        Ex : "=?UTF-8?B?QWxlcnRlIGVtcGxvaQ==?=" → "Alerte emploi"
        """
        parts = _decode_header(raw)
        decoded = []
        for part, charset in parts:
            if isinstance(part, bytes):
                decoded.append(
                    part.decode(charset or "utf-8", errors="replace")
                )
            else:
                decoded.append(str(part))
        return " ".join(decoded)

    def _get_html_body(self, msg: email.message.Message) -> str:
        """
        Extrait la partie HTML d'un email multipart.

        Les emails modernes sont "multipart/alternative" :
        ils contiennent une version texte ET une version HTML.
        On prend le HTML car il contient les liens et la structure.
        """
        html_parts = []
        text_parts = []

        if msg.is_multipart():
            for part in msg.walk():
                ct = part.get_content_type()
                if ct == "text/html":
                    charset = part.get_content_charset() or "utf-8"
                    payload = part.get_payload(decode=True)
                    if payload:
                        html_parts.append(
                            payload.decode(charset, errors="replace")
                        )
                elif ct == "text/plain":
                    charset = part.get_content_charset() or "utf-8"
                    payload = part.get_payload(decode=True)
                    if payload:
                        text_parts.append(
                            payload.decode(charset, errors="replace")
                        )
        else:
            charset = msg.get_content_charset() or "utf-8"
            payload = msg.get_payload(decode=True)
            if payload:
                if msg.get_content_type() == "text/html":
                    html_parts.append(
                        payload.decode(charset, errors="replace")
                    )
                else:
                    text_parts.append(
                        payload.decode(charset, errors="replace")
                    )

        return (
            "\n".join(html_parts)
            or "\n".join(text_parts)
        )

    def _detect_source(self, sender: str) -> Optional[str]:
        """
        Détecte le service d'alerte depuis l'adresse de l'expéditeur.
        Retourne le nom lisible ou None si inconnu.
        """
        sender_lower = sender.lower()
        for domain, (name, _) in SENDER_MAP.items():
            if domain in sender_lower:
                return name
        return None

    def _get_parser(self, sender: str) -> str:
        """Retourne le nom de la méthode de parsing adaptée."""
        sender_lower = sender.lower()
        for domain, (_, parser) in SENDER_MAP.items():
            if domain in sender_lower:
                return parser
        return "_parse_generic"

    def _looks_like_job_alert(self, subject: str) -> bool:
        """
        Heuristique : est-ce que le sujet ressemble à une alerte emploi ?
        Pour attraper les alertes de sites non listés dans SENDER_MAP.
        """
        keywords = [
            "alerte emploi", "offre d'emploi", "offres d'emploi",
            "job alert", "new jobs", "nouvelles offres",
            "alerte offre", "job matching",
        ]
        subject_lower = subject.lower()
        return any(kw in subject_lower for kw in keywords)

    # ------------------------------------------------------------------
    # Parsers HTML
    # ------------------------------------------------------------------

    def _make_id(self, url: str) -> str:
        """Génère un ID stable depuis une URL."""
        return (
            "email_" + hashlib.md5(url.encode()).hexdigest()[:12]
        )

    def _parse_linkedin(
        self, html: str, source_name: str
    ) -> list[JobOffer]:
        """
        Parse un email d'alerte LinkedIn.

        Structure typique d'un email LinkedIn :
        - Chaque offre est dans une cellule <td>
        - Le titre est un lien vers linkedin.com/jobs/view/XXXXXXXX
        - La société et le lieu suivent en texte brut

        Exemple :
          <a href="https://www.linkedin.com/jobs/view/3456789?...">
            Administrateur Système
          </a>
          <br>Tech Company · Toulouse, France
        """
        soup = BeautifulSoup(html, "html.parser")
        offers = []

        # Trouver tous les liens vers des offres LinkedIn
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if "linkedin.com/jobs/view/" not in href:
                continue

            title = a_tag.get_text(strip=True)
            if not title or len(title) < 3:
                continue

            # Nettoyer l'URL (supprimer les paramètres de tracking)
            clean_url = href.split("?")[0]

            # Chercher société + lieu dans les éléments voisins
            company = None
            location = None
            parent = a_tag.find_parent(["td", "div", "li", "article"])
            if parent:
                # Le texte après le lien contient souvent
                # "Société · Lieu" ou "Société\nLieu"
                context = parent.get_text(" | ", strip=True)
                # Supprimer le titre pour ne garder que le contexte
                context = context.replace(title, "").strip(" |·\n")
                parts = re.split(r"[·|•\n]+", context)
                parts = [p.strip() for p in parts if p.strip()]
                if parts:
                    company = parts[0]
                if len(parts) > 1:
                    location = parts[1]

            offers.append(JobOffer(
                id=self._make_id(clean_url),
                title=title,
                company=company,
                location=location,
                contract=None,
                salary=None,
                description="",
                url=clean_url,
                source=f"email_alert:{source_name}",
                published_at=None,
            ))

        logger.debug(f"LinkedIn parser : {len(offers)} offre(s)")
        return offers

    def _parse_indeed(
        self, html: str, source_name: str
    ) -> list[JobOffer]:
        """
        Parse un email d'alerte Indeed.

        Indeed envoie des emails avec des liens de tracking
        (rc/clk?jk=...) qui redirigent vers les offres.
        Le titre est généralement en gras dans le lien.
        """
        soup = BeautifulSoup(html, "html.parser")
        offers = []

        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            # Liens Indeed : rc/clk, viewjob, /rc/
            if not re.search(
                r"indeed\.com/(rc/clk|viewjob|/rc/)", href, re.I
            ):
                continue

            # Le titre peut être dans un <b> ou directement dans <a>
            b_tag = a_tag.find("b")
            title = (b_tag or a_tag).get_text(strip=True)
            if not title or len(title) < 3:
                continue

            # Contexte autour du lien
            company, location = None, None
            parent = a_tag.find_parent(["td", "div", "tr"])
            if parent:
                # Indeed met souvent société et ville dans des <span>
                spans = parent.find_all("span")
                texts = [
                    s.get_text(strip=True)
                    for s in spans
                    if s.get_text(strip=True)
                ]
                # Heuristique : 1er span = société, 2ème = lieu
                if texts:
                    company = texts[0] if texts[0] != title else None
                if len(texts) > 1:
                    location = texts[1]

            offers.append(JobOffer(
                id=self._make_id(href),
                title=title,
                company=company,
                location=location,
                contract=None,
                salary=None,
                description="",
                url=href,
                source=f"email_alert:{source_name}",
                published_at=None,
            ))

        logger.debug(f"Indeed parser : {len(offers)} offre(s)")
        return offers

    def _parse_generic(
        self, html: str, source_name: str
    ) -> list[JobOffer]:
        """
        Parser générique pour les autres services.

        Stratégie :
          1. Trouver tous les liens qui ressemblent à des offres d'emploi
          2. Extraire le texte du lien comme titre
          3. Chercher le contexte (société, lieu) autour du lien

        C'est moins précis que les parsers dédiés mais fonctionne
        pour la majorité des services.
        """
        soup = BeautifulSoup(html, "html.parser")
        offers = []

        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]

            # Vérifier si l'URL ressemble à une offre d'emploi
            if not JOB_URL_RE.search(href):
                continue

            title = a_tag.get_text(strip=True)
            # Ignorer les liens avec des titres trop courts ou
            # qui sont des boutons ("Postuler", "Apply", etc.)
            if not title or len(title) < 5:
                continue
            if title.lower() in {
                "postuler", "apply", "voir l'offre", "en savoir plus",
                "voir plus", "voir", "cliquez ici", "click here",
            }:
                continue

            # Chercher contexte (société/lieu) dans le parent
            company, location = None, None
            for ancestor in [a_tag.parent, a_tag.find_parent(["td", "div"])]:
                if not ancestor:
                    continue
                context = ancestor.get_text(" | ", strip=True)
                context = context.replace(title, "").strip(" |")
                # Chercher des patterns de lieu (ville, code postal...)
                loc_match = re.search(
                    r"([A-Z][a-zéèêà]+(?:[-\s][A-Z][a-zéèêà]+)*)"
                    r"\s*(?:\(\d{2}\)|\d{5})?",
                    context,
                )
                if loc_match:
                    location = loc_match.group(0).strip()
                break

            offers.append(JobOffer(
                id=self._make_id(href),
                title=title,
                company=company,
                location=location,
                contract=None,
                salary=None,
                description="",
                url=href,
                source=f"email_alert:{source_name}",
                published_at=None,
            ))

        # Dédoublonnage par URL
        seen: set[str] = set()
        unique = []
        for o in offers:
            if o.url not in seen:
                seen.add(o.url)
                unique.append(o)

        logger.debug(
            f"Parser générique ({source_name}) : {len(unique)} offre(s)"
        )
        return unique

    # ------------------------------------------------------------------
    # Point d'entrée
    # ------------------------------------------------------------------

    def search(
        self, keywords: list[str], locations: list[dict]
    ) -> list[JobOffer]:
        """
        Connexion IMAP → lecture des emails d'alerte →
        extraction des offres → liste de JobOffer.

        Les keywords et locations ne sont pas utilisés directement ici
        (les alertes email ont déjà leurs propres filtres configurés
        sur chaque plateforme). On filtre quand même par score ensuite.
        """
        if not HAS_BS4:
            logger.error(
                "beautifulsoup4 requis. Lance : pip install beautifulsoup4"
            )
            return []

        all_offers: list[JobOffer] = []
        seen_ids: set[str] = set()

        try:
            mail = self._connect()
            email_list = self._fetch_alert_emails(mail)
            mail.logout()
        except imaplib.IMAP4.error as e:
            logger.error(
                f"Erreur IMAP : {e}\n"
                "→ Vérifie IMAP_EMAIL, IMAP_PASSWORD et IMAP_HOST dans .env\n"
                "→ Pour Gmail : utilise un mot de passe d'application"
            )
            return []
        except Exception as e:
            logger.error(f"Connexion IMAP échouée : {e}")
            return []

        for uid, sender, html_body in email_list:
            source_name = (
                self._detect_source(sender) or "Inconnu"
            )
            parser_name = self._get_parser(sender)
            parser = getattr(self, parser_name)

            try:
                offers = parser(html_body, source_name)
            except Exception as e:
                logger.warning(
                    f"Erreur parsing email ({source_name}) : {e}"
                )
                continue

            for offer in offers:
                if offer.id not in seen_ids:
                    seen_ids.add(offer.id)
                    all_offers.append(offer)

            # Petite pause entre emails
            time.sleep(0.1)

        logger.info(
            f"Email alerts : {len(all_offers)} offres extraites "
            f"depuis {len(email_list)} email(s)"
        )
        return all_offers
