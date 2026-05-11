"""
Source : API officielle France Travail (ex-Pôle Emploi)

API gratuite, légale, la plus complète pour les offres françaises.

Inscription : https://francetravail.io/inscription
  → Crée une application, active "Offres d'emploi v2"
  → Copie Client ID et Client Secret dans .env
"""

import os
import time
import logging
import requests
from typing import Optional

from bot.models import JobOffer
from bot.sources.base import JobSource

logger = logging.getLogger(__name__)

TOKEN_URL = (
    "https://entreprise.francetravail.fr/connexion/oauth2/"
    "access_token?realm=%2Fpartenaire"
)
SEARCH_URL = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"

CONTRACT_LABELS = {
    "CDI": "CDI", "CDD": "CDD", "MIS": "Intérim",
    "ALT": "Alternance", "SAI": "Saisonnier",
}


class FranceTravailSource(JobSource):
    name = "france_travail"

    def __init__(self, config: dict):
        super().__init__(config)
        self.client_id = os.getenv("FRANCE_TRAVAIL_CLIENT_ID")
        self.client_secret = os.getenv("FRANCE_TRAVAIL_CLIENT_SECRET")
        self._token: Optional[str] = None
        self._token_expiry: float = 0

    def is_available(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def _get_token(self) -> Optional[str]:
        """Obtient ou renouvelle le token OAuth2 (valable ~30 min)."""
        if not self.is_available():
            logger.error("France Travail : clés API manquantes dans .env")
            return None

        if self._token and time.time() < self._token_expiry:
            return self._token

        try:
            resp = requests.post(
                TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "scope": "api_offresdemploiv2 o2dsoffre",
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            self._token = data["access_token"]
            expires = data.get("expires_in", 1800) - 60
            self._token_expiry = time.time() + expires
            logger.debug("France Travail : token obtenu")
            return self._token
        except requests.RequestException as e:
            logger.error(f"France Travail auth : {e}")
            return None

    def _search_one(
        self, keyword: str, commune_code: str, distance_km: int,
        contract_types: list[str], days_published: int,
    ) -> list[dict]:
        token = self._get_token()
        if not token:
            return []

        params = {
            "motsCles": keyword,
            "commune": commune_code,
            "distance": distance_km,
            "publieeDepuis": days_published,
            "range": f"0-{min(self.max_results - 1, 149)}",
            "sort": "1",
        }
        if contract_types:
            params["typeContrat"] = ",".join(contract_types)

        try:
            resp = requests.get(
                SEARCH_URL,
                params=params,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
                timeout=15,
            )
            if resp.status_code not in (200, 206):
                logger.warning(
                    f"France Travail : HTTP {resp.status_code} "
                    f"pour '{keyword}'"
                )
                return []
            return resp.json().get("resultats", [])
        except requests.RequestException as e:
            logger.error(f"France Travail requête : {e}")
            return []

    def _parse(self, raw: dict) -> Optional[JobOffer]:
        offer_id = raw.get("id", "")
        if not offer_id:
            return None
        try:
            lieu = raw.get("lieuTravail", {})
            location = " ".join(
                filter(None, [lieu.get("libelle"), lieu.get("codePostal")])
            )
            salaire = raw.get("salaire", {})
            contrat_code = raw.get("typeContrat", "")
            url = (
                raw.get("origineOffre", {}).get("urlOrigine")
                or (
                    "https://candidat.francetravail.fr"
                    f"/offres/recherche/detail/{offer_id}"
                )
            )
            return JobOffer(
                id=f"ft_{offer_id}",
                title=raw.get("intitule", "Sans titre"),
                company=raw.get("entreprise", {}).get("nom"),
                location=location or None,
                contract=(
                    CONTRACT_LABELS.get(contrat_code, contrat_code) or None
                ),
                salary=salaire.get("libelle") if salaire else None,
                description=raw.get("description", ""),
                url=url,
                source=self.name,
                published_at=(
                    raw.get("dateCreation") or raw.get("dateActualisation")
                ),
                raw_data=raw,
            )
        except Exception as e:
            logger.debug(f"France Travail parse error : {e}")
            return None

    def search(self, keywords: list[str], locations: list[dict]) -> list[JobOffer]:
        search_cfg = self.config.get("search", {})
        distance_km = search_cfg.get("distance_km", 30)
        contract_types = search_cfg.get("contract_types", [])
        days_published = search_cfg.get("days_published", 7)

        offers: list[JobOffer] = []
        seen: set[str] = set()
        total = len(keywords) * len(locations)
        n = 0

        for keyword in keywords:
            for loc in locations:
                n += 1
                logger.info(f"[FT {n}/{total}] '{keyword}' @ {loc['name']}")
                for raw in self._search_one(
                    keyword, loc["commune_code"],
                    distance_km, contract_types, days_published,
                ):
                    offer = self._parse(raw)
                    if offer and offer.id not in seen:
                        seen.add(offer.id)
                        offers.append(offer)
                if n < total:
                    time.sleep(0.4)

        # Recherche remote séparée
        if search_cfg.get("include_remote", True):
            for keyword in keywords[:5]:
                for raw in self._search_one(
                    f"{keyword} télétravail", "75056",
                    0, contract_types, days_published,
                ):
                    offer = self._parse(raw)
                    if offer and offer.id not in seen:
                        seen.add(offer.id)
                        offers.append(offer)
                time.sleep(0.3)

        logger.info(f"France Travail : {len(offers)} offres uniques")
        return offers
