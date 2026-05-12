"""
Source : Careerjet API

Careerjet est un agrégateur d'offres d'emploi avec une API REST publique
et GRATUITE — pas de clé API requise. C'est rare, on en profite.

Il couvre bien la France et les offres IT.

API publique, sans inscription :
  → https://public.api.careerjet.net/search
  → Aucun compte, aucune clé nécessaire
  → Juste un "affid" (affiliate ID) qu'on peut laisser vide

Paramètres utiles :
  - keywords     : mots-clés
  - location     : ville ou région
  - affid        : ton ID d'affilié (laisser vide = OK)
  - locale_code  : fr_FR pour la France en français
  - pagesize     : nombre de résultats par page (max 20)
  - page         : numéro de page
  - sort         : "date" ou "relevance"

Documentation :
  → https://www.careerjet.fr/partners/api/

Note : L'API retourne HTTP, pas HTTPS. On force HTTPS dans les URLs.
"""

import time
import logging
import requests
from typing import Optional

from bot.models import JobOffer
from bot.sources.base import JobSource

logger = logging.getLogger(__name__)

BASE_URL = "http://public.api.careerjet.net/search"  # HTTPS non supporté


class CareerjetSource(JobSource):
    name = "careerjet"

    def __init__(self, config: dict):
        super().__init__(config)
        import os
        self.affid = os.getenv("CAREERJET_AFFID", "")
        self._req_count = 0
        self._req_ok = 0
        self._req_err = 0
        self._conn_error = False
        self._error_logged = False

    def is_available(self) -> bool:
        # Toujours disponible — pas de clé requise
        return True

    def _search_one(
        self, keyword: str, location_name: str
    ) -> list[dict]:
        """
        Requête GET simple vers l'API publique Careerjet.

        La réponse contient :
          {
            "type": "JOBS",
            "hits": 142,           // total d'offres trouvées
            "jobs": [
              {
                "url": "https://...",
                "title": "Admin Système",
                "locations": "Toulouse, France",
                "date": "2024-01-15",
                "description": "...",
                "company": "Tech SA",
                "salary": "30-35k€"
              }
            ]
          }
        """
        self._req_count += 1
        params = {
            "keywords": keyword,
            "location": location_name,
            "locale_code": "fr_FR",
            "pagesize": min(self.max_results, 20),
            "page": 1,
            "sort": "date",
        }
        if self.affid:
            params["affid"] = self.affid

        try:
            resp = requests.get(BASE_URL, params=params, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                self._req_ok += 1
                if data.get("type") == "JOBS":
                    return data.get("jobs", [])
                return []
            self._req_err += 1
            if not self._error_logged:
                self._error_logged = True
                logger.warning(
                    f"Careerjet HTTP {resp.status_code} "
                    f"pour '{keyword}' @ {location_name}"
                )
            else:
                logger.debug(
                    f"Careerjet HTTP {resp.status_code} "
                    f"('{keyword}' @ {location_name})"
                )
            return []
        except requests.ConnectionError as e:
            self._req_err += 1
            self._conn_error = True
            if not self._error_logged:
                self._error_logged = True
                logger.warning(
                    "Careerjet indisponible : connexion refusée "
                    "à public.api.careerjet.net"
                )
                logger.debug(f"Careerjet erreur réseau : {e}")
            return []
        except requests.RequestException as e:
            self._req_err += 1
            if not self._error_logged:
                self._error_logged = True
                logger.warning(f"Careerjet erreur réseau : {e}")
            else:
                logger.debug(f"Careerjet erreur réseau : {e}")
            return []

    def _parse(self, raw: dict) -> Optional[JobOffer]:
        """
        Transforme un résultat Careerjet en JobOffer.

        Careerjet n'a pas d'ID propre — on utilise l'URL comme clé.
        """
        try:
            url = raw.get("url", "")
            if not url:
                return None

            import hashlib
            short_id = hashlib.md5(url.encode()).hexdigest()[:12]

            return JobOffer(
                id=f"cj_{short_id}",
                title=raw.get("title", "Sans titre"),
                company=raw.get("company") or None,
                location=raw.get("locations") or None,
                contract=None,  # Careerjet ne fournit pas le type de contrat
                salary=raw.get("salary") or None,
                description=raw.get("description", ""),
                url=url,
                source=self.name,
                published_at=raw.get("date"),
                raw_data=raw,
            )
        except Exception as e:
            logger.debug(f"Careerjet parse error : {e}")
            return None

    def search(
        self, keywords: list[str], locations: list[dict]
    ) -> list[JobOffer]:
        self._req_count = 0
        self._req_ok = 0
        self._req_err = 0
        self._conn_error = False
        self._error_logged = False

        offers: list[JobOffer] = []
        seen: set[str] = set()
        total = len(keywords) * len(locations)
        n = 0

        for keyword in keywords:
            if self._conn_error:
                break
            for loc in locations:
                if self._conn_error:
                    break
                n += 1
                logger.debug(
                    f"[Careerjet {n}/{total}] "
                    f"'{keyword}' @ {loc['name']}"
                )
                for raw in self._search_one(keyword, loc["name"]):
                    offer = self._parse(raw)
                    if offer and offer.id not in seen:
                        seen.add(offer.id)
                        offers.append(offer)

                if n < total and not self._conn_error:
                    time.sleep(0.3)

        diag = (
            "connexion refusée à public.api.careerjet.net"
            if self._conn_error else ""
        )
        self.stats = {
            "requests":    self._req_count,
            "success":     self._req_ok,
            "no_results":  0,
            "errors":      self._req_err,
            "error_codes": (
                f"réseau ×{self._req_err}" if self._req_err else ""
            ),
            "diagnosis":   diag,
            "offers":      len(offers),
        }
        return offers
