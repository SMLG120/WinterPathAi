"""Route explanation codes and localized (EN/FR) texts.

Wording rule: never call a route or sidewalk safe, cleared, ice-free or wheelchair accessible.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import EvidenceState

E = EvidenceState

#: code -> (evidence_state, en, fr). Texts use str.format placeholders.
CATALOG: dict[str, tuple[EvidenceState, str, str]] = {
    "SHORTEST_DISTANCE": (
        E.UNKNOWN,
        "Shortest legal walking distance on the mapped pedestrian network. Sidewalk winter "
        "conditions on this route are not verified.",
        "Plus courte distance de marche autorisée sur le réseau piéton cartographié. L'état "
        "hivernal des trottoirs de ce trajet n'est pas vérifié.",
    ),
    "WINTER_AWARE_COST": (
        E.UNKNOWN,
        "Balances walking time against known disruptions, reports and risk estimates where "
        "available. It does not guarantee sidewalk conditions.",
        "Équilibre le temps de marche avec les perturbations connues, les signalements et les "
        "estimations de risque lorsqu'elles existent. L'état des trottoirs n'est pas garanti.",
    ),
    "IDENTICAL_TO_SHORTEST": (
        E.UNKNOWN,
        "The winter-aware route is the same as the shortest route.",
        "Le trajet adapté à l'hiver est identique au trajet le plus court.",
    ),
    "EXCLUDES_CONFIRMED_CLOSURE": (
        E.CONFIRMED,
        "{n} officially permitted closure(s) that block pedestrian passage were excluded from "
        "routing.",
        "{n} fermeture(s) autorisée(s) officiellement qui bloquent le passage piéton ont été "
        "exclues du calcul.",
    ),
    "AVOIDS_CONFIRMED_DISRUPTION": (
        E.CONFIRMED,
        "Avoids {n} officially permitted work zone(s) on the shortest route.",
        "Évite {n} zone(s) de travaux autorisée(s) officiellement sur le trajet le plus court.",
    ),
    "PASSES_CONFIRMED_DISRUPTION": (
        E.CONFIRMED,
        "Passes {n} officially permitted work zone(s); passage is not stated as blocked.",
        "Passe par {n} zone(s) de travaux autorisée(s); le passage n'est pas indiqué comme bloqué.",
    ),
    "AVOIDS_POSSIBLE_CLOSURE": (
        E.UNKNOWN,
        "Avoids {n} officially permitted closure(s) that block pedestrian passage but whose "
        "schedule at this time is unknown.",
        "Évite {n} fermeture(s) autorisée(s) officiellement qui bloquent le passage piéton, mais "
        "dont l'horaire à ce moment est inconnu.",
    ),
    "PASSES_POSSIBLE_CLOSURE": (
        E.UNKNOWN,
        "Passes {n} officially permitted closure(s) that block pedestrian passage; whether they "
        "are in effect at this time is unknown.",
        "Passe par {n} fermeture(s) autorisée(s) officiellement qui bloquent le passage piéton; "
        "on ignore si elles sont en vigueur à ce moment.",
    ),
    "AVOIDS_UNVERIFIED_REPORT": (
        E.UNVERIFIED_REPORT,
        "Avoids {n} area(s) with unverified public reports (311 or community).",
        "Évite {n} secteur(s) avec des signalements publics non vérifiés (311 ou communauté).",
    ),
    "PASSES_UNVERIFIED_REPORT": (
        E.UNVERIFIED_REPORT,
        "Passes {n} area(s) with unverified public reports (311 or community).",
        "Passe par {n} secteur(s) avec des signalements publics non vérifiés (311 ou communauté).",
    ),
    "LOWER_MODELED_RISK": (
        E.MODEL_ESTIMATE,
        "Lower estimated winter-report risk than the shortest route (model estimate, not an "
        "observation of sidewalk conditions).",
        "Risque estimé de signalements hivernaux plus faible que le trajet le plus court "
        "(estimation de modèle, pas une observation de l'état des trottoirs).",
    ),
    "RISK_UNKNOWN_SHARE": (
        E.UNKNOWN,
        "{pct}% of this route has no risk data. Unknown is not the same as low risk.",
        "{pct} % de ce trajet n'a aucune donnée de risque. Inconnu ne signifie pas risque faible.",
    ),
    "RISK_LAYER_UNAVAILABLE": (
        E.UNKNOWN,
        "No winter risk layer is available; risk is unknown on every segment.",
        "Aucune couche de risque hivernal n'est disponible; le risque est inconnu partout.",
    ),
    "STEP_FREE_TAGGED_ONLY": (
        E.UNVERIFIED_REPORT,
        "Uses only segments tagged step-free in community-mapped data (OpenStreetMap). Tags may "
        "be outdated; snow and ice conditions are not verified.",
        "N'utilise que des segments indiqués sans marche dans des données cartographiées par la "
        "communauté (OpenStreetMap). Ces indications peuvent être périmées; l'état de la neige et "
        "de la glace n'est pas vérifié.",
    ),
    "REDUCED_MOBILITY_SPEED": (
        E.MODEL_ESTIMATE,
        "Times assume a walking speed of {speed} m/s and steps are avoided where possible.",
        "Les durées supposent une vitesse de marche de {speed} m/s et les marches sont évitées si "
        "possible.",
    ),
    "INCLUDES_STEPS": (
        E.UNVERIFIED_REPORT,
        "This route includes mapped steps.",
        "Ce trajet comprend des marches cartographiées.",
    ),
    "SIMULATED_DATA": (
        E.SIMULATED,
        "SIMULATED: computed on synthetic demo data, not real streets or conditions.",
        "SIMULÉ : calculé sur des données de démonstration synthétiques, pas sur des rues ou des "
        "conditions réelles.",
    ),
}


@dataclass(frozen=True, slots=True)
class Explanation:
    code: str
    text: str
    evidence_state: EvidenceState

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "text": self.text, "evidence_state": self.evidence_state.value}


def explain(code: str, locale: str = "en", **kwargs: object) -> Explanation:
    state, en, fr = CATALOG[code]
    template = fr if locale == "fr" else en
    return Explanation(code, template.format(**kwargs), state)
