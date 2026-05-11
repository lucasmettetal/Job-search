"""
Gestionnaire de configuration — lit et écrit config.yaml.

Principe : CE MODULE est le seul qui touche config.yaml.
L'interface Streamlit passe par ces fonctions, jamais directement
par le fichier. Ça évite les erreurs de format et les pertes de données.

Utilisation :
    from bot.config_manager import ConfigManager
    cfg = ConfigManager()
    cfg.keywords           # liste des mots-clés
    cfg.set_keywords([...])  # modifie + sauvegarde
"""

import copy
import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

CONFIG_PATH = Path("config.yaml")

# Structure par défaut — utilisée si config.yaml est absent
_DEFAULTS: dict = {
    "search": {
        "keywords": [
            "administrateur système",
            "technicien systèmes réseaux",
            "support informatique",
            "cybersécurité junior",
            "analyste SOC",
        ],
        "locations": [
            {"name": "Toulouse",  "commune_code": "31555"},
            {"name": "Montauban", "commune_code": "82121"},
        ],
        "distance_km": 30,
        "contract_types": ["CDI", "CDD", "ALT", "MIS"],
        "days_published": 7,
        "include_remote": True,
    },
    "sources": {
        "france_travail": {"enabled": True,  "max_results_per_keyword": 50},
        "adzuna":         {"enabled": False, "max_results_per_keyword": 25},
        "jooble":         {"enabled": False, "max_results_per_keyword": 20},
        "careerjet":      {"enabled": True,  "max_results_per_keyword": 20},
        "themuse":        {"enabled": False, "max_results_per_keyword": 30},
        "brave_search":   {"enabled": False, "max_results_per_keyword": 15},
        "email_alerts":   {
            "enabled": False,
            "days_back": 2,
            "mark_as_read": False,
            "mailbox": "INBOX",
        },
    },
    "scoring": {
        "weights": {
            "title_keyword_match": 4,
            "desc_keyword_match": 1,
            "junior_bonus": 2,
            "remote_bonus": 1,
            "alternance_bonus": 2,
            "cyber_bonus": 3,
            "experience_penalty": -3,
        },
        "min_score": 2,
    },
    "email": {
        "recipient": "",
        "subject": "[JobBot] {nb_offres} nouvelles offres - {date}",
        "max_offers_in_email": 25,
        "min_offers_to_send": 1,
    },
    "database": {"path": "data/jobs.db"},
    "app": {"title": "JobBot Dashboard", "db_path": "data/jobs.db"},
    "logging": {"level": "INFO", "file": "logs/bot.log"},
}

# Métadonnées des sources (pour l'interface)
SOURCE_META: dict[str, dict] = {
    "france_travail": {
        "label":       "France Travail",
        "emoji":       "🇫🇷",
        "description": "API officielle ex-Pôle Emploi — meilleure source FR",
        "requires":    ["FRANCE_TRAVAIL_CLIENT_ID", "FRANCE_TRAVAIL_CLIENT_SECRET"],
        "free":        False,
        "signup_url":  "https://francetravail.io/inscription",
        "quota":       "Illimité",
    },
    "adzuna": {
        "label":       "Adzuna",
        "emoji":       "🔍",
        "description": "Agrégateur international, bonne couverture France",
        "requires":    ["ADZUNA_APP_ID", "ADZUNA_APP_KEY"],
        "free":        False,
        "signup_url":  "https://developer.adzuna.com/signup",
        "quota":       "250 req/jour",
    },
    "jooble": {
        "label":       "Jooble",
        "emoji":       "🌐",
        "description": "Agrégateur mondial, offres de nombreux sites FR",
        "requires":    ["JOOBLE_API_KEY"],
        "free":        False,
        "signup_url":  "https://jooble.org/api/about",
        "quota":       "~500 req/mois",
    },
    "careerjet": {
        "label":       "Careerjet",
        "emoji":       "📋",
        "description": "Agrégateur — API publique gratuite, sans inscription",
        "requires":    [],
        "free":        True,
        "signup_url":  "",
        "quota":       "Illimité",
    },
    "themuse": {
        "label":       "The Muse",
        "emoji":       "✨",
        "description": "Offres remote/internationales — surtout US",
        "requires":    [],
        "free":        True,
        "signup_url":  "",
        "quota":       "Illimité",
    },
    "brave_search": {
        "label":       "Brave Search",
        "emoji":       "🦁",
        "description": "Fallback moteur de recherche — trouve des offres sur tout site",
        "requires":    ["BRAVE_API_KEY"],
        "free":        False,
        "signup_url":  "https://brave.com/search/api/",
        "quota":       "2 000 req/mois",
    },
    "email_alerts": {
        "label":       "Alertes Email",
        "emoji":       "📧",
        "description": "Lit les alertes LinkedIn, Indeed, HelloWork reçues par email",
        "requires":    ["IMAP_EMAIL", "IMAP_PASSWORD"],
        "free":        True,
        "signup_url":  "",
        "quota":       "—",
    },
}


class ConfigManager:
    """
    Gestionnaire de configuration.

    Usage :
        cfg = ConfigManager()          # charge config.yaml
        kw = cfg.keywords              # lit les mots-clés
        cfg.set_keywords(["SOC", "sysadmin"])  # sauvegarde

    Toutes les modifications sont écrites immédiatement dans config.yaml.
    """

    def __init__(self, path: Path = CONFIG_PATH):
        self._path = path
        self._data: dict = {}
        self.load()

    # ------------------------------------------------------------------
    # Chargement / sauvegarde
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Charge config.yaml. Si absent, utilise les valeurs par défaut."""
        if self._path.exists():
            with open(self._path, encoding="utf-8") as f:
                loaded = yaml.safe_load(f) or {}
            # Fusion avec les défauts pour les clés manquantes
            self._data = self._deep_merge(_DEFAULTS, loaded)
        else:
            self._data = copy.deepcopy(_DEFAULTS)
            logger.warning(
                f"config.yaml introuvable — valeurs par défaut utilisées"
            )

    def save(self) -> None:
        """Écrit la configuration dans config.yaml."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            yaml.dump(
                self._data,
                f,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
                indent=2,
            )
        logger.info(f"Configuration sauvegardée : {self._path}")

    def get_raw(self) -> dict:
        """Retourne une copie de la config complète (lecture seule)."""
        return copy.deepcopy(self._data)

    # ------------------------------------------------------------------
    # Mots-clés
    # ------------------------------------------------------------------

    @property
    def keywords(self) -> list[str]:
        return self._data.get("search", {}).get("keywords", [])

    def set_keywords(self, keywords: list[str]) -> None:
        """Remplace la liste de mots-clés et sauvegarde."""
        cleaned = [k.strip() for k in keywords if k.strip()]
        self._data.setdefault("search", {})["keywords"] = cleaned
        self.save()

    # ------------------------------------------------------------------
    # Localisations
    # ------------------------------------------------------------------

    @property
    def locations(self) -> list[dict]:
        return self._data.get("search", {}).get("locations", [])

    def set_locations(self, locations: list[dict]) -> None:
        """
        locations = liste de dicts :
          [{"name": "Toulouse", "commune_code": "31555"}, ...]
        """
        self._data.setdefault("search", {})["locations"] = locations
        self.save()

    # ------------------------------------------------------------------
    # Paramètres de recherche
    # ------------------------------------------------------------------

    @property
    def distance_km(self) -> int:
        return self._data.get("search", {}).get("distance_km", 30)

    def set_distance_km(self, km: int) -> None:
        self._data.setdefault("search", {})["distance_km"] = int(km)
        self.save()

    @property
    def days_published(self) -> int:
        return self._data.get("search", {}).get("days_published", 7)

    def set_days_published(self, days: int) -> None:
        self._data.setdefault("search", {})["days_published"] = int(days)
        self.save()

    @property
    def include_remote(self) -> bool:
        return self._data.get("search", {}).get("include_remote", True)

    def set_include_remote(self, value: bool) -> None:
        self._data.setdefault("search", {})["include_remote"] = bool(value)
        self.save()

    @property
    def contract_types(self) -> list[str]:
        return self._data.get("search", {}).get(
            "contract_types", ["CDI", "CDD", "ALT", "MIS"]
        )

    def set_contract_types(self, types: list[str]) -> None:
        self._data.setdefault("search", {})["contract_types"] = types
        self.save()

    # ------------------------------------------------------------------
    # Sources
    # ------------------------------------------------------------------

    def is_source_enabled(self, name: str) -> bool:
        return (
            self._data.get("sources", {})
            .get(name, {})
            .get("enabled", name == "france_travail")
        )

    def set_source_enabled(self, name: str, enabled: bool) -> None:
        """Active ou désactive une source."""
        self._data.setdefault("sources", {}).setdefault(name, {})[
            "enabled"
        ] = bool(enabled)
        self.save()

    def get_source_config(self, name: str) -> dict:
        return self._data.get("sources", {}).get(name, {})

    def set_source_max_results(self, name: str, n: int) -> None:
        self._data.setdefault("sources", {}).setdefault(name, {})[
            "max_results_per_keyword"
        ] = int(n)
        self.save()

    def set_email_alerts_config(
        self, days_back: int, mark_as_read: bool, mailbox: str
    ) -> None:
        cfg = self._data.setdefault("sources", {}).setdefault(
            "email_alerts", {}
        )
        cfg["days_back"] = int(days_back)
        cfg["mark_as_read"] = bool(mark_as_read)
        cfg["mailbox"] = mailbox.strip() or "INBOX"
        self.save()

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    @property
    def min_score(self) -> int:
        return self._data.get("scoring", {}).get("min_score", 2)

    def set_min_score(self, score: int) -> None:
        self._data.setdefault("scoring", {})["min_score"] = int(score)
        self.save()

    # ------------------------------------------------------------------
    # Email quotidien
    # ------------------------------------------------------------------

    @property
    def email_config(self) -> dict:
        return self._data.get("email", {})

    def set_email_config(
        self,
        recipient: str,
        subject: str = "",
        max_offers: int = 25,
        min_offers: int = 1,
    ) -> None:
        cfg = self._data.setdefault("email", {})
        cfg["recipient"] = recipient.strip()
        if subject:
            cfg["subject"] = subject.strip()
        cfg["max_offers_in_email"] = int(max_offers)
        cfg["min_offers_to_send"] = int(min_offers)
        self.save()

    # ------------------------------------------------------------------
    # Base de données
    # ------------------------------------------------------------------

    @property
    def db_path(self) -> str:
        return self._data.get("database", {}).get("path", "data/jobs.db")

    # ------------------------------------------------------------------
    # Utilitaires
    # ------------------------------------------------------------------

    @staticmethod
    def _deep_merge(base: dict, override: dict) -> dict:
        """
        Fusionne deux dicts de façon récursive.
        override écrase base, mais les sous-dicts sont fusionnés.
        """
        result = copy.deepcopy(base)
        for key, val in override.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(val, dict)
            ):
                result[key] = ConfigManager._deep_merge(result[key], val)
            else:
                result[key] = copy.deepcopy(val)
        return result
