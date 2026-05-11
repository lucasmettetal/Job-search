"""
Classe de base pour toutes les sources d'offres d'emploi.

Toute nouvelle source DOIT hériter de JobSource et implémenter :
  - search(keywords, locations) → list[JobOffer]
  - is_available() → bool  (la source est-elle configurée ?)

Ce contrat garantit que le reste du code (source_loader, main.py)
peut appeler n'importe quelle source de façon identique.
"""

from abc import ABC, abstractmethod
from bot.models import JobOffer


class JobSource(ABC):
    """
    Classe abstraite : socle commun à toutes les sources.

    ABC (Abstract Base Class) = impossible d'instancier directement cette
    classe. On doit obligatoirement créer une sous-classe qui implémente
    les méthodes marquées @abstractmethod.
    """

    name: str = "unknown"

    def __init__(self, config: dict):
        """
        config = le dict complet de config.yaml.
        Chaque source lit sa propre section via :
            config["sources"]["nom_source"]
        """
        self.config = config
        self.source_config = config.get("sources", {}).get(self.name, {})
        # Limite de résultats par mot-clé (protège les quotas API)
        self.max_results = self.source_config.get("max_results_per_keyword", 25)

    @abstractmethod
    def search(self, keywords: list[str], locations: list[dict]) -> list[JobOffer]:
        """
        Récupère des offres pour les mots-clés et localisations donnés.

        Paramètres :
          - keywords  : liste de chaînes, ex. ["admin système", "SOC junior"]
          - locations : liste de dicts avec au moins la clé 'name',
                        ex. [{"name": "Toulouse", "commune_code": "31555"}]

        Retourne une liste de JobOffer (peut être vide).
        """
        ...

    def is_available(self) -> bool:
        """
        Retourne True si la source est prête à fonctionner.
        Surcharge cette méthode dans les sources qui nécessitent
        des clés API — retourne False si les clés manquent.
        """
        return True

    def __str__(self) -> str:
        return f"Source({self.name})"
