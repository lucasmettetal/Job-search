"""
Gestionnaire de secrets — lit et écrit le fichier .env.

RÈGLES DE SÉCURITÉ :
  1. Les valeurs réelles ne sont JAMAIS retournées à l'interface.
     Seule mask_value() est utilisée pour afficher.
  2. .env est toujours local — jamais committé sur Git.
  3. Ce module vérifie que .env est dans .gitignore.
  4. Les secrets ne transitent pas par un serveur ou une API.

Utilisation :
    from bot.secrets_manager import SecretsManager
    sm = SecretsManager()
    sm.set("ADZUNA_APP_KEY", "abc123")   # écrit dans .env
    sm.has("ADZUNA_APP_KEY")             # True
    sm.mask("ADZUNA_APP_KEY")            # "abc•••123"
"""

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

ENV_PATH = Path(".env")
GITIGNORE_PATH = Path(".gitignore")

# Définition de tous les secrets attendus par le bot
# Regroupés par source pour l'affichage dans l'interface
SECRETS_REGISTRY: dict[str, dict] = {
    # --- France Travail ---
    "FRANCE_TRAVAIL_CLIENT_ID": {
        "label":       "Client ID",
        "source":      "france_travail",
        "description": "Identifiant application France Travail",
        "is_password": False,
        "required_if_enabled": True,
    },
    "FRANCE_TRAVAIL_CLIENT_SECRET": {
        "label":       "Client Secret",
        "source":      "france_travail",
        "description": "Clé secrète France Travail",
        "is_password": True,
        "required_if_enabled": True,
    },
    # --- Adzuna ---
    "ADZUNA_APP_ID": {
        "label":       "App ID",
        "source":      "adzuna",
        "description": "Identifiant application Adzuna",
        "is_password": False,
        "required_if_enabled": True,
    },
    "ADZUNA_APP_KEY": {
        "label":       "App Key",
        "source":      "adzuna",
        "description": "Clé API Adzuna",
        "is_password": True,
        "required_if_enabled": True,
    },
    # --- Jooble ---
    "JOOBLE_API_KEY": {
        "label":       "API Key",
        "source":      "jooble",
        "description": "Clé API Jooble",
        "is_password": True,
        "required_if_enabled": True,
    },
    # --- Careerjet ---
    "CAREERJET_AFFID": {
        "label":       "Affiliate ID (optionnel)",
        "source":      "careerjet",
        "description": "ID affilié Careerjet (facultatif)",
        "is_password": False,
        "required_if_enabled": False,
    },
    # --- Brave Search ---
    "BRAVE_API_KEY": {
        "label":       "API Key",
        "source":      "brave_search",
        "description": "Clé API Brave Search",
        "is_password": True,
        "required_if_enabled": True,
    },
    # --- Email sortant (SMTP) ---
    "EMAIL_SENDER": {
        "label":       "Adresse Gmail",
        "source":      "email_smtp",
        "description": "Adresse Gmail pour envoyer le rapport quotidien",
        "is_password": False,
        "required_if_enabled": False,
    },
    "EMAIL_APP_PASSWORD": {
        "label":       "Mot de passe d'application Gmail",
        "source":      "email_smtp",
        "description": "Mot de passe d'application (16 car.) — pas ton vrai mdp",
        "is_password": True,
        "required_if_enabled": False,
    },
    # --- IMAP (alertes email) ---
    "IMAP_EMAIL": {
        "label":       "Adresse email IMAP",
        "source":      "email_alerts",
        "description": "Adresse de la boîte à surveiller",
        "is_password": False,
        "required_if_enabled": True,
    },
    "IMAP_PASSWORD": {
        "label":       "Mot de passe IMAP",
        "source":      "email_alerts",
        "description": "Mot de passe d'application Gmail (ou mdp IMAP)",
        "is_password": True,
        "required_if_enabled": True,
    },
    "IMAP_HOST": {
        "label":       "Serveur IMAP (optionnel)",
        "source":      "email_alerts",
        "description": "Auto-détecté pour Gmail. Ex: imap.orange.fr",
        "is_password": False,
        "required_if_enabled": False,
    },
}


class SecretsManager:
    """
    Gère les secrets dans le fichier .env.

    Le fichier .env est simple : une paire KEY=valeur par ligne.
    On lit, on modifie, on réécrit le fichier en préservant
    les lignes existantes (commentaires compris).
    """

    def __init__(self, env_path: Path = ENV_PATH):
        self._path = env_path
        self.ensure_gitignore()

    # ------------------------------------------------------------------
    # Lecture
    # ------------------------------------------------------------------

    def _parse(self) -> dict[str, str]:
        """
        Lit le fichier .env et retourne un dict {KEY: valeur}.

        Format .env :
          KEY=valeur
          # commentaire (ignoré)
          AUTRE_KEY=autre valeur
        """
        result: dict[str, str] = {}
        if not self._path.exists():
            return result
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, val = line.partition("=")
                result[key.strip()] = val.strip()
        return result

    def get(self, key: str) -> Optional[str]:
        """
        Retourne la valeur réelle d'un secret.

        ⚠️  N'utilise cette fonction QUE pour passer la valeur
        à une API ou un module — jamais pour l'afficher.
        Utilise mask() pour l'affichage.
        """
        # Priorité : variables d'environnement du système > .env
        env_val = os.environ.get(key)
        if env_val:
            return env_val
        return self._parse().get(key)

    def has(self, key: str) -> bool:
        """Retourne True si le secret est défini et non vide."""
        val = self.get(key)
        return bool(val and val.strip())

    def get_all_keys(self) -> list[str]:
        """Liste des clés présentes dans .env."""
        return list(self._parse().keys())

    # ------------------------------------------------------------------
    # Écriture
    # ------------------------------------------------------------------

    def set(self, key: str, value: str) -> None:
        """
        Définit ou met à jour un secret dans .env.

        Stratégie d'écriture :
          - Si la clé existe déjà → on la remplace sur la même ligne
          - Si elle n'existe pas → on l'ajoute à la fin
          - Les commentaires et autres clés sont préservés
        """
        value = value.strip()
        if not value:
            logger.warning(f"Valeur vide pour {key} — non sauvegardée")
            return

        lines = []
        found = False

        if self._path.exists():
            for line in self._path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if (
                    stripped
                    and not stripped.startswith("#")
                    and "=" in stripped
                ):
                    k = stripped.split("=", 1)[0].strip()
                    if k == key:
                        lines.append(f"{key}={value}")
                        found = True
                        continue
                lines.append(line)

        if not found:
            lines.append(f"{key}={value}")

        self._path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        logger.info(f"Secret '{key}' sauvegardé dans {self._path}")

    def set_many(self, updates: dict[str, str]) -> None:
        """Sauvegarde plusieurs secrets en une seule écriture."""
        # Charger l'état actuel
        current = {}
        preserved_lines = []  # lignes à garder telles quelles (commentaires)

        if self._path.exists():
            for line in self._path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    k, _, v = stripped.partition("=")
                    current[k.strip()] = v.strip()
                else:
                    preserved_lines.append(line)

        # Appliquer les mises à jour
        current.update({k: v.strip() for k, v in updates.items() if v.strip()})

        # Reconstruire le fichier
        lines = preserved_lines + [
            f"{k}={v}" for k, v in current.items()
        ]
        self._path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        logger.info(
            f"{len(updates)} secret(s) sauvegardés dans {self._path}"
        )

    def delete(self, key: str) -> bool:
        """
        Supprime un secret du fichier .env.
        Retourne True si la clé existait.
        """
        if not self._path.exists():
            return False

        lines = []
        found = False
        for line in self._path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if (
                stripped
                and not stripped.startswith("#")
                and "=" in stripped
            ):
                k = stripped.split("=", 1)[0].strip()
                if k == key:
                    found = True
                    continue  # Supprime cette ligne
            lines.append(line)

        if found:
            self._path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            logger.info(f"Secret '{key}' supprimé de {self._path}")
        return found

    # ------------------------------------------------------------------
    # Masquage — pour l'affichage dans l'interface
    # ------------------------------------------------------------------

    def mask(self, key: str) -> str:
        """
        Retourne une version masquée d'un secret pour l'affichage.

        Exemples :
          "sk-abc123xyz789" → "sk-•••••••••789"
          "abcd"            → "••••"
          ""                → "(non défini)"
        """
        val = self.get(key)
        return self.mask_value(val)

    @staticmethod
    def mask_value(val: Optional[str]) -> str:
        """
        Masque une valeur pour l'affichage.
        Statique : utilisable sans instancier SecretsManager.
        """
        if not val:
            return "_(non défini)_"
        val = val.strip()
        n = len(val)
        if n <= 4:
            return "•" * n
        visible = min(3, n // 4)
        return val[:visible] + "•" * (n - visible * 2) + val[-visible:]

    def status_for_source(self, source_name: str) -> dict:
        """
        Retourne l'état de configuration d'une source.

        Retourne un dict :
          {
            "configured": bool,   # toutes les clés requises présentes
            "missing":    [...],  # clés manquantes
            "optional_missing": [...],
          }
        """
        missing_required = []
        missing_optional = []

        for key, meta in SECRETS_REGISTRY.items():
            if meta["source"] != source_name:
                continue
            if not self.has(key):
                if meta["required_if_enabled"]:
                    missing_required.append(key)
                else:
                    missing_optional.append(key)

        return {
            "configured": len(missing_required) == 0,
            "missing": missing_required,
            "optional_missing": missing_optional,
        }

    # ------------------------------------------------------------------
    # Sécurité — .gitignore
    # ------------------------------------------------------------------

    def ensure_gitignore(self) -> bool:
        """
        Vérifie que '.env' est bien dans .gitignore.
        L'ajoute si ce n'est pas le cas.
        Retourne True si une modification a été faite.
        """
        gitignore = GITIGNORE_PATH

        if gitignore.exists():
            content = gitignore.read_text(encoding="utf-8")
            # Chercher ".env" comme ligne seule (pas juste un commentaire)
            lines = [l.strip() for l in content.splitlines()]
            if ".env" in lines:
                return False  # Déjà présent
        else:
            content = ""

        # Ajouter .env au .gitignore
        addition = "\n# Secrets — ne jamais committer\n.env\n"
        gitignore.write_text(content + addition, encoding="utf-8")
        logger.warning(
            ".env ajouté à .gitignore — tes secrets sont protégés"
        )
        return True

    def env_file_exists(self) -> bool:
        return self._path.exists()

    def create_env_from_example(self) -> bool:
        """
        Crée .env à partir de .env.example si .env n'existe pas encore.
        Retourne True si créé.
        """
        example = Path(".env.example")
        if not self._path.exists() and example.exists():
            self._path.write_text(
                example.read_text(encoding="utf-8"), encoding="utf-8"
            )
            logger.info(".env créé depuis .env.example")
            return True
        return False

    # ------------------------------------------------------------------
    # Tests de connexion
    # ------------------------------------------------------------------

    def test_smtp(self) -> tuple[bool, str]:
        """
        Teste la connexion SMTP Gmail.
        Retourne (succès, message).
        """
        import smtplib
        sender = self.get("EMAIL_SENDER")
        password = self.get("EMAIL_APP_PASSWORD")

        if not sender or not password:
            return False, "EMAIL_SENDER ou EMAIL_APP_PASSWORD non défini"

        try:
            with smtplib.SMTP("smtp.gmail.com", 587) as s:
                s.ehlo()
                s.starttls()
                s.ehlo()
                s.login(sender, password)
            return True, f"✅ Connexion SMTP réussie pour {sender}"
        except smtplib.SMTPAuthenticationError:
            return (
                False,
                "❌ Authentification échouée — "
                "utilise un mot de passe d'application Gmail",
            )
        except Exception as e:
            return False, f"❌ Erreur SMTP : {e}"

    def test_imap(self) -> tuple[bool, str]:
        """
        Teste la connexion IMAP.
        Retourne (succès, message).
        """
        import imaplib

        imap_email = self.get("IMAP_EMAIL") or ""
        password = self.get("IMAP_PASSWORD")

        if not imap_email or not password:
            return False, "IMAP_EMAIL ou IMAP_PASSWORD non défini"

        # Auto-détection du serveur
        from bot.sources.email_alerts import IMAP_AUTO
        domain = imap_email.split("@")[-1].lower()
        host_env = self.get("IMAP_HOST")
        host, port = IMAP_AUTO.get(domain, ("", 993))
        host = host_env or host

        if not host:
            return (
                False,
                f"Serveur IMAP inconnu pour '@{domain}'. "
                "Renseigne IMAP_HOST manuellement.",
            )

        try:
            mail = imaplib.IMAP4_SSL(host, int(port))
            mail.login(imap_email, password)
            mail.select("INBOX")
            mail.logout()
            return True, f"✅ Connexion IMAP réussie ({host})"
        except imaplib.IMAP4.error as e:
            return (
                False,
                f"❌ Erreur IMAP : {e}\n"
                "→ Utilise un mot de passe d'application Gmail",
            )
        except Exception as e:
            return False, f"❌ Erreur : {e}"
