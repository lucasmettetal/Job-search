"""
Source : Brave Search API (fallback moteur de recherche)

Brave Search offre une API de recherche web qui peut trouver
des offres d'emploi sur n'importe quel site sans scraping direct.

On construit des requêtes ciblées vers des sites d'offres légaux :
  → site:apec.fr OR site:monster.fr OR site:welcometothejungle.com
  → On récupère les URLs et titres, pas le contenu complet

Avantages :
  - Légal (on passe par l'API officielle Brave)
  - Couvre des sites qu'on n'intègrerait pas directement
  - Fallback utile si les autres APIs tombent

Limites :
  - On n'a que le titre et un extrait (pas la description complète)
  - L'utilisateur doit cliquer pour voir le détail de l'offre
  - Quota : 2 000 requêtes/mois en gratuit

Inscription :
  → https://brave.com/search/api/
  → "Try it for free" → 2 000 requêtes/mois
  → Mets ta clé dans .env : BRAVE_API_KEY=xxxx

Documentation :
  → https://api.search.brave.com/app/documentation/web-search/get-started

Alternatives :
  - Google Custom Search API (100 req/jour gratuit)
    → Clé : GOOGLE_SEARCH_API_KEY + GOOGLE_SEARCH_CX
    → L'implémentation Google est en commentaire en bas de ce fichier
"""

import os
import time
import logging
import requests
from typing import Optional

from bot.models import JobOffer
from bot.sources.base import JobSource

logger = logging.getLogger(__name__)

BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"

# Sites d'offres à cibler dans les requêtes (légaux, publics)
JOB_SITES = [
    "apec.fr",
    "welcometothejungle.com",
    "monster.fr",
    "regionsjob.com",
    "cadremploi.fr",
]


class BraveSearchSource(JobSource):
    name = "brave_search"

    def __init__(self, config: dict):
        super().__init__(config)
        self.api_key = os.getenv("BRAVE_API_KEY")

    def is_available(self) -> bool:
        return bool(self.api_key)

    def _build_query(
        self, keyword: str, location_name: str
    ) -> str:
        """
        Construit une requête de recherche web ciblée.

        Exemple de requête générée :
          "administrateur système" Toulouse
          site:apec.fr OR site:welcometothejungle.com
        """
        sites_filter = " OR ".join(
            f"site:{s}" for s in JOB_SITES
        )
        return f'"{keyword}" {location_name} ({sites_filter})'

    def _search_web(self, query: str) -> list[dict]:
        """
        Appelle l'API Brave Search avec la requête construite.

        La réponse contient des "web results" avec :
          - title : titre de la page
          - url   : lien direct
          - description : extrait de la page
        """
        try:
            resp = requests.get(
                BRAVE_URL,
                params={
                    "q": query,
                    "count": min(self.max_results, 20),
                    "country": "FR",
                    "search_lang": "fr",
                    "freshness": "pw",  # pw = past week
                },
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "X-Subscription-Token": self.api_key,
                },
                timeout=15,
            )
            if resp.status_code == 200:
                web = resp.json().get("web", {})
                return web.get("results", [])
            logger.warning(
                f"Brave Search : HTTP {resp.status_code} "
                f"pour '{query[:50]}...'"
            )
            return []
        except requests.RequestException as e:
            logger.error(f"Brave Search requête : {e}")
            return []

    def _parse(self, raw: dict, keyword: str) -> Optional[JobOffer]:
        """
        Transforme un résultat web en JobOffer approximatif.

        On n'a que le titre et la description de la page web,
        pas les champs structurés d'une API emploi.
        Le score sera calculé sur ces données par le module scoring.

        Structure d'un résultat Brave :
          {
            "title": "Administrateur Système - Toulouse | APEC",
            "url": "https://www.apec.fr/offres-emploi/...",
            "description": "CDI - Toulouse. Missions : ...",
            "age": "2 hours ago"
          }
        """
        try:
            url = raw.get("url", "")
            title = raw.get("title", "")
            if not url or not title:
                return None

            # Nettoyer le titre (souvent "Poste | NomSite")
            clean_title = title.split("|")[0].split("-")[0].strip()
            if not clean_title:
                clean_title = title

            import hashlib
            short_id = hashlib.md5(url.encode()).hexdigest()[:12]

            # Identifier la source originale depuis l'URL
            source_site = next(
                (s for s in JOB_SITES if s in url), "web"
            )

            return JobOffer(
                id=f"brave_{short_id}",
                title=clean_title,
                company=None,
                location=None,
                contract=None,
                salary=None,
                description=raw.get("description", ""),
                url=url,
                source=f"{self.name}:{source_site}",
                published_at=raw.get("age"),
                raw_data=raw,
            )
        except Exception as e:
            logger.debug(f"Brave Search parse error : {e}")
            return None

    def search(
        self, keywords: list[str], locations: list[dict]
    ) -> list[JobOffer]:
        """
        On limite les requêtes Brave à 5 mots-clés × 3 villes max
        pour ne pas épuiser le quota mensuel de 2 000 requêtes.
        """
        offers: list[JobOffer] = []
        seen: set[str] = set()

        # Mots-clés prioritaires seulement
        priority_kw = keywords[:5]
        priority_loc = locations[:3]
        total = len(priority_kw) * len(priority_loc)
        n = 0

        for keyword in priority_kw:
            for loc in priority_loc:
                n += 1
                query = self._build_query(keyword, loc["name"])
                logger.debug(
                    f"[Brave {n}/{total}] {query[:60]}..."
                )
                for raw in self._search_web(query):
                    offer = self._parse(raw, keyword)
                    if offer and offer.id not in seen:
                        seen.add(offer.id)
                        offers.append(offer)

                if n < total:
                    time.sleep(1.0)  # Pause plus longue = quota protégé

        logger.info(f"Brave Search : {len(offers)} résultats")
        return offers


# ===========================================================================
#  Variante Google Custom Search (alternative à Brave)
# ===========================================================================
#
#  Si tu préfères utiliser Google à la place de Brave :
#
#  1. Crée une clé API sur https://console.cloud.google.com/
#     → Active "Custom Search API"
#     → GOOGLE_SEARCH_API_KEY=xxxx dans .env
#
#  2. Crée un moteur de recherche sur https://programmablesearchengine.google.com/
#     → Configure pour chercher sur les sites job listés
#     → GOOGLE_SEARCH_CX=xxxx dans .env (c'est l'ID du moteur)
#
#  3. Remplace la méthode _search_web par :
#
#  GOOGLE_URL = "https://www.googleapis.com/customsearch/v1"
#
#  def _search_web_google(self, query: str) -> list[dict]:
#      import os
#      api_key = os.getenv("GOOGLE_SEARCH_API_KEY")
#      cx = os.getenv("GOOGLE_SEARCH_CX")
#      if not api_key or not cx:
#          return []
#      resp = requests.get(
#          GOOGLE_URL,
#          params={"key": api_key, "cx": cx, "q": query,
#                  "num": 10, "lr": "lang_fr"},
#          timeout=15,
#      )
#      if resp.status_code == 200:
#          return resp.json().get("items", [])
#      return []
