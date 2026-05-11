"""
Source : Adzuna API

Adzuna est un agrégateur d'offres d'emploi avec une vraie API REST
gratuite (jusqu'à 250 requêtes/jour en tier gratuit).
Il couvre bien la France et les offres tech/IT.

Inscription et clés API :
  → https://developer.adzuna.com/signup
  → Crée une application (gratuit)
  → Récupère ton App ID et App Key
  → Mets-les dans .env :
      ADZUNA_APP_ID=xxxx
      ADZUNA_APP_KEY=xxxx

Documentation officielle :
  → https://developer.adzuna.com/docs/search
"""

import os
import time
import logging
import requests
from typing import Optional

from bot.models import JobOffer
from bot.sources.base import JobSource

logger = logging.getLogger(__name__)

# Endpoint France (le pays est dans l'URL)
BASE_URL = "https://api.adzuna.com/v1/api/jobs/fr/search/1"


class AdzunaSource(JobSource):
    name = "adzuna"

    def __init__(self, config: dict):
        super().__init__(config)
        self.app_id = os.getenv("ADZUNA_APP_ID")
        self.app_key = os.getenv("ADZUNA_APP_KEY")

    def is_available(self) -> bool:
        return bool(self.app_id and self.app_key)

    def _search_one(
        self, keyword: str, location_name: str
    ) -> list[dict]:
        """
        Une requête Adzuna = un mot-clé + une ville.

        Paramètres clés :
          - what        : mots-clés (cherchés dans titre + description)
          - where       : ville ou région
          - distance    : rayon en km
          - results_per_page : nombre de résultats (max 50)
          - sort_by     : date (le plus récent en premier)
        """
        distance_km = self.config.get("search", {}).get(
            "distance_km", 30
        )
        days = self.config.get("search", {}).get("days_published", 7)

        params = {
            "app_id": self.app_id,
            "app_key": self.app_key,
            "what": keyword,
            "where": location_name,
            "distance": distance_km,
            "results_per_page": min(self.max_results, 50),
            "sort_by": "date",
            "content-type": "application/json",
        }

        # Filtre "publiée depuis N jours" via max_days_old
        if days:
            params["max_days_old"] = days

        try:
            resp = requests.get(BASE_URL, params=params, timeout=15)
            if resp.status_code == 200:
                return resp.json().get("results", [])
            logger.warning(
                f"Adzuna : HTTP {resp.status_code} "
                f"pour '{keyword}' @ {location_name}"
            )
            return []
        except requests.RequestException as e:
            logger.error(f"Adzuna requête : {e}")
            return []

    def _parse(self, raw: dict) -> Optional[JobOffer]:
        """
        Transforme un résultat Adzuna en JobOffer.

        Structure d'un résultat Adzuna :
          {
            "id": "12345",
            "title": "Administrateur Système",
            "company": {"display_name": "Tech SA"},
            "location": {"display_name": "Toulouse, Occitanie"},
            "contract_type": "permanent",     # permanent / contract
            "contract_time": "full_time",
            "salary_min": 28000, "salary_max": 35000,
            "description": "...",
            "redirect_url": "https://...",
            "created": "2024-01-15T10:00:00Z"
          }
        """
        try:
            offer_id = str(raw.get("id", ""))
            if not offer_id:
                return None

            salary = None
            s_min = raw.get("salary_min")
            s_max = raw.get("salary_max")
            if s_min and s_max:
                salary = f"{int(s_min):,}€ – {int(s_max):,}€/an"
            elif s_min:
                salary = f"À partir de {int(s_min):,}€/an"

            # Adzuna utilise "permanent" pour CDI, "contract" pour CDD
            contract_map = {
                "permanent": "CDI",
                "contract": "CDD/Contrat",
                "part_time": "Temps partiel",
            }
            contract_raw = raw.get("contract_type", "")
            contract = contract_map.get(contract_raw, contract_raw) or None

            return JobOffer(
                id=f"adzuna_{offer_id}",
                title=raw.get("title", "Sans titre"),
                company=raw.get("company", {}).get("display_name"),
                location=raw.get("location", {}).get("display_name"),
                contract=contract,
                salary=salary,
                description=raw.get("description", ""),
                url=raw.get("redirect_url", ""),
                source=self.name,
                published_at=raw.get("created"),
                raw_data=raw,
            )
        except Exception as e:
            logger.debug(f"Adzuna parse error : {e}")
            return None

    def search(
        self, keywords: list[str], locations: list[dict]
    ) -> list[JobOffer]:
        offers: list[JobOffer] = []
        seen: set[str] = set()
        total = len(keywords) * len(locations)
        n = 0

        for keyword in keywords:
            for loc in locations:
                n += 1
                logger.debug(
                    f"[Adzuna {n}/{total}] "
                    f"'{keyword}' @ {loc['name']}"
                )
                for raw in self._search_one(keyword, loc["name"]):
                    offer = self._parse(raw)
                    if offer and offer.id not in seen:
                        seen.add(offer.id)
                        offers.append(offer)

                if n < total:
                    time.sleep(0.5)

        logger.info(f"Adzuna : {len(offers)} offres uniques")
        return offers
