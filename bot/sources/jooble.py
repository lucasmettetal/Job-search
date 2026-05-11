"""
Source : Jooble API

Jooble est un agrégateur mondial d'offres d'emploi.
Son API est simple : une seule requête POST avec mots-clés + ville.
Il couvre bien la France et indexe beaucoup de sources (Indeed, LinkedIn...).

Inscription et clé API :
  → https://jooble.org/api/about
  → Remplis le formulaire (gratuit pour usage perso/test)
  → Tu reçois ta clé par email
  → Mets-la dans .env : JOOBLE_API_KEY=xxxx

Contrainte : quota généralement limité à ~500 requêtes/mois en gratuit.
On regroupe donc les mots-clés pour minimiser les appels.

Documentation :
  → https://jooble.org/api/about (très simple, 1 page)
"""

import os
import time
import logging
import requests
from typing import Optional

from bot.models import JobOffer
from bot.sources.base import JobSource

logger = logging.getLogger(__name__)


class JoobleSource(JobSource):
    name = "jooble"

    def __init__(self, config: dict):
        super().__init__(config)
        self.api_key = os.getenv("JOOBLE_API_KEY")

    def is_available(self) -> bool:
        return bool(self.api_key)

    def _search_one(
        self, keyword: str, location_name: str, page: int = 1
    ) -> list[dict]:
        """
        Jooble utilise POST (pas GET) avec un JSON dans le body.

        Structure du body :
          {
            "keywords": "administrateur système",
            "location": "Toulouse",
            "radius": "50",
            "page": 1,
            "datecreatedfrom": "2024-01-10"  // optionnel
          }

        La réponse contient :
          {
            "totalCount": 42,
            "jobs": [ {"title", "location", "snippet",
                       "salary", "source", "type",
                       "link", "company", "updated"} ]
          }
        """
        url = f"https://jooble.org/api/{self.api_key}"
        body = {
            "keywords": keyword,
            "location": location_name,
            "radius": str(
                self.config.get("search", {}).get("distance_km", 30)
            ),
            "page": page,
            "resultonpage": min(self.max_results, 20),
        }

        try:
            resp = requests.post(url, json=body, timeout=15)
            if resp.status_code == 200:
                return resp.json().get("jobs", [])
            logger.warning(
                f"Jooble : HTTP {resp.status_code} "
                f"pour '{keyword}' @ {location_name}"
            )
            return []
        except requests.RequestException as e:
            logger.error(f"Jooble requête : {e}")
            return []

    def _parse(self, raw: dict) -> Optional[JobOffer]:
        """
        Transforme un résultat Jooble en JobOffer.

        Jooble ne fournit pas d'ID propre — on utilise le lien
        comme identifiant unique.

        Structure d'un résultat Jooble :
          {
            "title": "Technicien Informatique",
            "location": "Toulouse, France",
            "snippet": "Description courte...",
            "salary": "2 500 € / mois",
            "source": "indeed.fr",          // site d'origine
            "type": "Temps plein",
            "link": "https://jooble.org/...",
            "company": "Tech SA",
            "updated": "2024-01-15T10:00:00"
          }
        """
        try:
            # On utilise le lien comme clé unique (Jooble n'a pas d'ID)
            link = raw.get("link", "")
            if not link:
                return None

            # Hash court du lien pour l'ID
            import hashlib
            short_id = hashlib.md5(
                link.encode()
            ).hexdigest()[:12]

            return JobOffer(
                id=f"jooble_{short_id}",
                title=raw.get("title", "Sans titre"),
                company=raw.get("company") or None,
                location=raw.get("location") or None,
                contract=raw.get("type") or None,
                salary=raw.get("salary") or None,
                description=raw.get("snippet", ""),
                url=link,
                source=self.name,
                published_at=raw.get("updated"),
                raw_data=raw,
            )
        except Exception as e:
            logger.debug(f"Jooble parse error : {e}")
            return None

    def search(
        self, keywords: list[str], locations: list[dict]
    ) -> list[JobOffer]:
        """
        Stratégie Jooble : on regroupe les mots-clés pour économiser
        les appels API. L'API Jooble supporte plusieurs mots-clés
        séparés par des virgules.

        On fait une requête par ville (pas par mot-clé) pour limiter
        la consommation du quota mensuel.
        """
        offers: list[JobOffer] = []
        seen: set[str] = set()

        # Regrouper tous les mots-clés en une seule chaîne
        # (Jooble cherche avec OU entre les termes)
        combined_keywords = " OR ".join(f'"{kw}"' for kw in keywords[:6])

        for loc in locations:
            logger.debug(
                f"[Jooble] mots-clés groupés @ {loc['name']}"
            )
            for raw in self._search_one(combined_keywords, loc["name"]):
                offer = self._parse(raw)
                if offer and offer.id not in seen:
                    seen.add(offer.id)
                    offers.append(offer)
            time.sleep(0.5)

        # Recherche remote séparée
        if self.config.get("search", {}).get("include_remote", True):
            for raw in self._search_one(
                f"{combined_keywords} télétravail", "France"
            ):
                offer = self._parse(raw)
                if offer and offer.id not in seen:
                    seen.add(offer.id)
                    offers.append(offer)

        logger.info(f"Jooble : {len(offers)} offres uniques")
        return offers
