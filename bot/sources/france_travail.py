"""
Source : API officielle France Travail (ex-Pôle Emploi)

API gratuite, légale, la plus complète pour les offres françaises.

Inscription : https://francetravail.io/inscription
  → Crée une application, active "Offres d'emploi v2"
  → Copie Client ID et Client Secret dans .env
"""

import json
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
SEARCH_URL = (
    "https://api.francetravail.io/partenaire/offresdemploi"
    "/v2/offres/search"
)

CONTRACT_LABELS = {
    "CDI": "CDI", "CDD": "CDD", "MIS": "Intérim",
    "ALT": "Alternance", "SAI": "Saisonnier",
}

# Valeurs acceptées par France Travail pour publieeDepuis
VALID_PUBLISHED = (1, 3, 7, 14, 31)

# Types de contrat valides pour l'API v2 — ALT (alternance) n'est pas accepté
_FT_VALID_CONTRACTS = frozenset({"CDI", "CDD", "MIS", "SAI"})


class FranceTravailSource(JobSource):
    name = "france_travail"

    def __init__(self, config: dict):
        super().__init__(config)
        self.client_id = os.getenv("FRANCE_TRAVAIL_CLIENT_ID")
        self.client_secret = os.getenv("FRANCE_TRAVAIL_CLIENT_SECRET")
        self._token: Optional[str] = None
        self._token_expiry: float = 0
        # Stats réinitialisées à chaque appel de search()
        self._req_count = 0
        self._req_ok = 0
        self._no_results = 0
        self._errors: list[tuple[int, str]] = []  # (status, body_snippet)
        self._diagnostic_done = False
        self._retry_warned = False

    def is_available(self) -> bool:
        return bool(self.client_id and self.client_secret)

    # ------------------------------------------------------------------
    # Token OAuth2
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Validation / sanitisation des paramètres
    # ------------------------------------------------------------------

    @staticmethod
    def _clamp_published(days: int) -> int:
        """
        France Travail n'accepte que 1, 3, 7, 14 ou 31 pour publieeDepuis.
        Sélectionne la valeur valide la plus proche.
        """
        return min(VALID_PUBLISHED, key=lambda v: abs(v - days))

    @staticmethod
    def _filter_contract_types(types: list[str]) -> list[str]:
        valid = [t for t in types if t in _FT_VALID_CONTRACTS]
        removed = [t for t in types if t not in _FT_VALID_CONTRACTS]
        if removed:
            logger.info(
                "France Travail : type(s) de contrat ignoré(s) : "
                f"{', '.join(removed)} "
                "— ALT n'est pas accepté par l'API, "
                "utilise le mot-clé 'alternance' à la place"
            )
        return valid

    # ------------------------------------------------------------------
    # Diagnostic : identifier la cause du HTTP 400
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_400_body(body: str) -> str:
        """
        Extrait le message d'erreur depuis la réponse JSON France Travail.

        Format habituel :
          {"message": "...", "msgErrors": [{"field": "...", "message": "..."}]}
        """
        if not body or not body.strip().startswith("{"):
            return body[:150] if body else "(corps vide)"
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return body[:150]

        # Erreurs par champ (le plus précis)
        msg_errors = data.get("msgErrors") or data.get("errors") or []
        if isinstance(msg_errors, list) and msg_errors:
            parts = []
            for e in msg_errors:
                if isinstance(e, dict):
                    field = e.get("field", "")
                    msg = e.get("message", "")
                    parts.append(f"{field}: {msg}" if field else msg)
            if parts:
                return " | ".join(parts)

        # Message générique
        msg = data.get("message") or data.get("error_description", "")
        return str(msg)[:200] if msg else body[:150]

    def _diagnose_400(self, body: str, params: dict) -> str:
        """Retourne un diagnostic lisible pour le résumé console."""
        detail = self._parse_400_body(body)

        # Indices dans le message de l'API
        low = (detail + str(params)).lower()
        if "typecontrat" in low or "typecontrat" in str(params).lower():
            return (
                f"typeContrat invalide ({params.get('typeContrat', '?')}) "
                f"— essaie CDI,CDD,MIS uniquement"
            )
        if "commune" in low:
            return (
                f"code commune invalide ({params.get('commune', '?')}) "
                f"— vérifie les codes INSEE dans config.yaml"
            )
        if "distance" in low:
            return "paramètre distance invalide"
        if "publieedepuis" in low or "publieedepuis" in str(params).lower():
            return (
                f"publieeDepuis invalide ({params.get('publieeDepuis')}) "
                f"— valeurs acceptées : 1, 3, 7, 14, 31"
            )
        if "range" in low:
            return f"paramètre range invalide ({params.get('range')})"
        if detail:
            return detail[:120]
        return "paramètres invalides — voir logs/jobbot_debug.log"

    def _run_diagnostic(self, keyword: str, token: str) -> None:
        """
        Teste deux requêtes minimales pour isoler la cause du HTTP 400 :
          1. motsCles seul (sans localisation ni contrat)
          2. motsCles + commune seule
        Appelée une seule fois, au premier échec.
        """
        if self._diagnostic_done:
            return
        self._diagnostic_done = True

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

        # Récupère le premier code commune disponible
        first_commune = (
            self.config.get("search", {})
            .get("locations", [{}])[0]
            .get("commune_code", "31555")
        )

        tests = [
            ("motsCles seul",   {"motsCles": keyword, "range": "0-4"}),
            ("+ commune seule", {
                "motsCles": keyword,
                "commune": first_commune,
                "range": "0-4",
            }),
        ]

        logger.debug("France Travail — lancement du diagnostic automatique")
        for label, params in tests:
            try:
                r = requests.get(
                    SEARCH_URL, params=params,
                    headers=headers, timeout=10,
                )
                if r.status_code in (200, 206):
                    count = len(r.json().get("resultats", []))
                    logger.debug(
                        f"  DIAG [{label}] → HTTP {r.status_code} OK "
                        f"({count} résultats)"
                    )
                else:
                    body = self._parse_400_body(r.text)
                    logger.debug(
                        f"  DIAG [{label}] → HTTP {r.status_code} : {body}"
                    )
                    logger.debug(
                        f"  DIAG [{label}] réponse complète : {r.text[:800]}"
                    )
            except Exception as e:
                logger.debug(f"  DIAG [{label}] échoué : {e}")

        logger.debug(
            "France Travail — diagnostic complet dans logs/jobbot_debug.log"
        )

    # ------------------------------------------------------------------
    # Requête API
    # ------------------------------------------------------------------

    def _search_one(
        self,
        keyword: str,
        commune_code: str,
        distance_km: int,
        contract_types: list[str],
        days_published: int,
        token: str,
    ) -> list[dict]:
        """
        Exécute une requête de recherche et retourne les résultats bruts.
        Gère le tracking des stats et la déduplication des erreurs.
        """
        self._req_count += 1

        params: dict = {
            "motsCles": keyword,
            "publieeDepuis": self._clamp_published(days_published),
            "range": f"0-{min(self.max_results - 1, 149)}",
            "sort": "1",
        }
        if commune_code:
            params["commune"] = commune_code
        if distance_km > 0 and commune_code:
            params["distance"] = distance_km
        if contract_types:
            params["typeContrat"] = ",".join(contract_types)

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

        try:
            resp = requests.get(
                SEARCH_URL,
                params=params,
                headers=headers,
                timeout=15,
            )
        except requests.RequestException as e:
            logger.error(f"France Travail requête réseau : {e}")
            self._errors.append((-1, str(e)))
            return []

        if resp.status_code == 204:
            self._no_results += 1
            return []

        if resp.status_code not in (200, 206):
            # Retry sans typeContrat si 400 et typeContrat présent dans params
            if resp.status_code == 400 and "typeContrat" in params:
                params_no_ct = {
                    k: v for k, v in params.items()
                    if k != "typeContrat"
                }
                logger.debug(
                    "France Travail 400 avec typeContrat"
                    " — retry sans typeContrat"
                )
                try:
                    resp_retry = requests.get(
                        SEARCH_URL,
                        params=params_no_ct,
                        headers=headers,
                        timeout=15,
                    )
                    if resp_retry.status_code in (200, 206):
                        if not self._retry_warned:
                            self._retry_warned = True
                            logger.info(
                                "France Travail : typeContrat désactivé "
                                "automatiquement pour cette requête"
                            )
                        self._req_ok += 1
                        return resp_retry.json().get("resultats", [])
                    if resp_retry.status_code == 204:
                        self._no_results += 1
                        return []
                    resp = resp_retry
                except requests.RequestException:
                    pass

            body = resp.text[:800] if resp.text else "(vide)"
            self._errors.append((resp.status_code, body))
            is_first = len(self._errors) == 1

            if is_first:
                # Premier échec → warning visible avec diagnostic
                diag = self._diagnose_400(body, params)
                logger.warning(
                    f"France Travail HTTP {resp.status_code} — "
                    f"{diag}"
                )
                logger.debug(
                    f"France Travail — paramètres envoyés : {params}"
                )
                logger.debug(
                    f"France Travail — réponse API : {body}"
                )
                # Lance le diagnostic automatique (appels minimaux)
                self._run_diagnostic(keyword, token)
            else:
                # Erreurs suivantes → debug seulement (pas de spam)
                logger.debug(
                    f"France Travail HTTP {resp.status_code} "
                    f"(#{len(self._errors)}, '{keyword}')"
                )
            return []

        self._req_ok += 1
        return resp.json().get("resultats", [])

    # ------------------------------------------------------------------
    # Parsing d'une offre
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Point d'entrée
    # ------------------------------------------------------------------

    def search(
        self, keywords: list[str], locations: list[dict]
    ) -> list[JobOffer]:
        # Réinitialiser les stats pour cet appel
        self._req_count = 0
        self._req_ok = 0
        self._no_results = 0
        self._errors = []
        self._diagnostic_done = False
        self._retry_warned = False

        token = self._get_token()
        if not token:
            self.stats = {
                "requests": 0, "success": 0, "errors": 1,
                "diagnosis": "impossible d'obtenir le token OAuth2",
            }
            return []

        search_cfg = self.config.get("search", {})
        distance_km = search_cfg.get("distance_km", 30)
        use_filter = self.source_config.get("use_contract_filter", False)
        raw_types = search_cfg.get("contract_types", [])
        contract_types = (
            self._filter_contract_types(raw_types) if use_filter else raw_types
        )
        days_published = search_cfg.get("days_published", 7)

        offers: list[JobOffer] = []
        seen: set[str] = set()
        total = len(keywords) * len(locations)
        n = 0

        for keyword in keywords:
            for loc in locations:
                n += 1
                # DEBUG uniquement — ne pollue pas la console
                logger.debug(
                    f"[FT {n}/{total}] '{keyword}' @ {loc['name']}"
                )
                for raw in self._search_one(
                    keyword,
                    loc.get("commune_code", ""),
                    distance_km,
                    contract_types,
                    days_published,
                    token,
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
                logger.debug(
                    f"[FT remote] '{keyword}' (télétravail, Paris)"
                )
                for raw in self._search_one(
                    f"{keyword} télétravail",
                    "75056",
                    0,
                    contract_types,
                    days_published,
                    token,
                ):
                    offer = self._parse(raw)
                    if offer and offer.id not in seen:
                        seen.add(offer.id)
                        offers.append(offer)
                time.sleep(0.3)

        # Construction du diagnostic final
        err_count = len(self._errors)
        if err_count > 0:
            first_status, first_body = self._errors[0]
            fake_params = self.config.get("search", {})
            diagnosis = self._diagnose_400(
                first_body,
                {"typeContrat": ",".join(contract_types)} if contract_types else {},
            )
            # Résumé des codes d'erreur
            codes: dict[int, int] = {}
            for status, _ in self._errors:
                codes[status] = codes.get(status, 0) + 1
            code_str = ", ".join(
                f"HTTP {s} ×{n}" for s, n in sorted(codes.items())
            )
        else:
            diagnosis = ""
            code_str = ""

        self.stats = {
            "requests":   self._req_count,
            "success":    self._req_ok,
            "no_results": self._no_results,
            "errors":     err_count,
            "error_codes": code_str,
            "diagnosis":  diagnosis,
            "offers":     len(offers),
        }

        return offers
