"""
Source : The Muse API

The Muse est une plateforme d'offres d'emploi axée sur les entreprises
tech, avec une API publique sans clé API pour la lecture.

⚠️  Limitation importante : The Muse est TRÈS axée États-Unis.
    Elle est utile ici uniquement pour les offres en REMOTE/télétravail
    ouvertes à l'international. Ne pas activer pour des recherches locales.

API publique, sans clé :
  → https://www.themuse.com/api/public/jobs
  → Pas d'inscription nécessaire

Paramètres :
  - page       : numéro de page (commence à 1)
  - category   : "IT & Data" est la plus pertinente pour nous
  - level      : "junior" pour filtrer les postes accessibles

Cas d'usage recommandé :
  → Activée uniquement si include_remote: true dans config.yaml
  → Cherche des postes junior en IT ouverts à l'international

Documentation :
  → https://www.themuse.com/developers/api/v2
"""

import time
import logging
import requests
from typing import Optional

from bot.models import JobOffer
from bot.sources.base import JobSource

logger = logging.getLogger(__name__)

BASE_URL = "https://www.themuse.com/api/public/jobs"

# Catégories The Muse pertinentes pour notre profil
TARGET_CATEGORIES = [
    "IT & Data",
    "Software Engineer",
]

# Niveaux de séniorité à cibler
TARGET_LEVELS = [
    "Entry Level",
    "Mid Level",
    "Internship",
]


class TheMuseSource(JobSource):
    name = "themuse"

    def __init__(self, config: dict):
        super().__init__(config)

    def is_available(self) -> bool:
        # Toujours disponible (API publique)
        # Mais on la désactive si include_remote est False
        return self.config.get("search", {}).get(
            "include_remote", True
        )

    def _fetch_page(
        self, category: str, level: str, page: int
    ) -> list[dict]:
        """
        Récupère une page de résultats The Muse.

        The Muse n'a pas de filtre par mots-clés dans l'API publique —
        on filtre par catégorie et niveau, puis on filtre par mots-clés
        sur notre side (dans search()).
        """
        params = {
            "category": category,
            "level": level,
            "page": page,
            "descending": "true",
        }

        try:
            resp = requests.get(BASE_URL, params=params, timeout=15)
            if resp.status_code == 200:
                return resp.json().get("results", [])
            logger.warning(
                f"TheMuse : HTTP {resp.status_code} "
                f"cat={category} level={level}"
            )
            return []
        except requests.RequestException as e:
            logger.error(f"TheMuse requête : {e}")
            return []

    def _parse(self, raw: dict) -> Optional[JobOffer]:
        """
        Structure d'un résultat The Muse :
          {
            "id": 12345,
            "name": "Junior DevOps Engineer",
            "locations": [{"name": "Remote"}],
            "categories": [{"name": "IT & Data"}],
            "levels": [{"name": "Entry Level"}],
            "company": {
              "name": "TechCorp",
              "industries": [...]
            },
            "refs": {"landing_page": "https://..."},
            "publication_date": "2024-01-15T00:00:00Z",
            "contents": "<p>Description HTML...</p>"
          }
        """
        try:
            offer_id = str(raw.get("id", ""))
            if not offer_id:
                return None

            # Localisation : Remote ou ville
            locations = raw.get("locations", [])
            location = (
                ", ".join(loc["name"] for loc in locations)
                if locations else "Remote"
            )

            # Niveau → type de contrat approximatif
            levels = raw.get("levels", [])
            level_names = [lv["name"] for lv in levels]
            contract = (
                "Alternance/Stage"
                if "Internship" in level_names
                else "CDI (Remote)"
            )

            # Nettoyage basique du HTML dans la description
            contents = raw.get("contents", "")
            description = (
                contents
                .replace("<p>", "").replace("</p>", "\n")
                .replace("<br>", "\n").replace("<br/>", "\n")
                .replace("<ul>", "").replace("</ul>", "")
                .replace("<li>", "• ").replace("</li>", "\n")
                .replace("<strong>", "").replace("</strong>", "")
            )

            url = raw.get("refs", {}).get(
                "landing_page", "https://www.themuse.com"
            )

            return JobOffer(
                id=f"muse_{offer_id}",
                title=raw.get("name", "Sans titre"),
                company=raw.get("company", {}).get("name"),
                location=location,
                contract=contract,
                salary=None,  # The Muse ne fournit pas les salaires
                description=description.strip(),
                url=url,
                source=self.name,
                published_at=raw.get("publication_date"),
                raw_data=raw,
            )
        except Exception as e:
            logger.debug(f"TheMuse parse error : {e}")
            return None

    def _matches_keywords(
        self, offer: JobOffer, keywords: list[str]
    ) -> bool:
        """
        Filtre post-récupération : vérifie qu'au moins un mot-clé
        apparaît dans le titre ou la description.

        Nécessaire car The Muse n'a pas de filtre mots-clés dans l'API.
        """
        text = (
            (offer.title or "") + " " + (offer.description or "")
        ).lower()
        return any(kw.lower() in text for kw in keywords)

    def search(
        self, keywords: list[str], locations: list[dict]
    ) -> list[JobOffer]:
        """
        The Muse : on récupère les offres IT junior/remote,
        puis on filtre par mots-clés côté client.
        """
        offers: list[JobOffer] = []
        seen: set[str] = set()
        max_pages = 3  # On limite pour ne pas surcharger

        for category in TARGET_CATEGORIES:
            for level in TARGET_LEVELS[:2]:  # Entry + Mid seulement
                for page in range(1, max_pages + 1):
                    results = self._fetch_page(category, level, page)
                    if not results:
                        break

                    for raw in results:
                        offer = self._parse(raw)
                        if (
                            offer
                            and offer.id not in seen
                            and self._matches_keywords(offer, keywords)
                        ):
                            seen.add(offer.id)
                            offers.append(offer)

                    if len(offers) >= self.max_results:
                        break
                    time.sleep(0.3)

        logger.info(f"TheMuse : {len(offers)} offres filtrées")
        return offers
