"""
Modèle de données : la structure d'une offre d'emploi.

On utilise un dataclass Python — c'est comme un "moule" qui définit
à quoi ressemble une offre d'emploi dans tout notre programme.
Chaque source (France Travail, etc.) devra remplir ce moule.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class JobOffer:
    """
    Représente une offre d'emploi.

    @dataclass génère automatiquement __init__, __repr__, etc.
    Optional[str] = le champ peut être None (pas renseigné).
    """
    id: str                          # Identifiant unique (fourni par la source)
    title: str                       # Intitulé du poste
    source: str                      # Nom de la source : "france_travail"
    url: str                         # Lien direct vers l'offre

    company: Optional[str] = None    # Nom de l'entreprise
    location: Optional[str] = None   # Ville / département
    contract: Optional[str] = None   # CDI, CDD, ALT...
    salary: Optional[str] = None     # Salaire (souvent absent)
    description: Optional[str] = None
    published_at: Optional[str] = None
    score: int = 0                   # Score calculé par le module scoring.py
    raw_data: dict = field(default_factory=dict)  # Données brutes (pour debug)

    def __str__(self) -> str:
        return f"[{self.score}pts] {self.title} @ {self.company} ({self.location})"
