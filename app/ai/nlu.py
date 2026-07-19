"""Lightweight natural-language understanding shared by both engines.

The same intent / language / facility detection grounds the Claude prompt
(so the server only computes and sends *relevant* context - cheaper and more
factual) and drives the offline fallback engine directly.

Matching rules: multi-word markers match as substrings; single-word markers
match with a left word boundary (so "eat" matches "eating" but never "seat").
Matchers are compiled once at import time.

Supported languages: English, Spanish, French (the three FIFA World Cup 2026
host-country languages).
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from re import Pattern

LANGUAGES = ("en", "es", "fr")


def _compile(markers: Iterable[str]) -> Pattern[str]:
    parts = []
    for marker in sorted(markers, key=len, reverse=True):
        escaped = re.escape(marker)
        # Single words get a left boundary; phrases match as substrings.
        parts.append(escaped if (" " in marker or "'" in marker) else rf"\b{escaped}")
    return re.compile("|".join(parts))


_ES_MARKERS = [
    "dónde", "donde", "cómo", "como llego", "llegar", "baño", "banos", "puerta",
    "estadio", "hola", "gracias", "cerca", "ayuda", "necesito", "silla de ruedas",
    "comida", "agua", "por favor", "está", "qué", "cuál", "hay", "partido", "salida",
]
_FR_MARKERS = [
    "où", "bonjour", "merci", "toilettes", "porte", "stade", "près", "aide",
    "besoin", "fauteuil", "nourriture", "eau", "comment", "aller", "s'il vous",
    "je cherche", "sortie", "quelle", "itinéraire", "chemin",
]
_ES_CHARS = set("ñ¿¡")
_FR_CHARS = set("çœùêâî")

_FACILITY_PATTERNS = {
    ftype: _compile(words)
    for ftype, words in {
        "restroom": {"restroom", "toilet", "bathroom", "washroom", "wc", "baño", "bano", "banos", "baños", "sanitario", "toilettes"},
        "water_refill": {"water refill", "water fountain", "refill", "fountain", "agua", "fuente", "eau potable", "fontaine", "gourde"},
        "first_aid": {"first aid", "medic", "doctor", "nurse", "injur", "hurt", "primeros auxilios", "médico", "medico", "enfermer", "infirmier", "secours", "blessé", "herido"},
        "food": {"food", "eat", "hungry", "snack", "restaurant", "comida", "comer", "hambre", "manger", "faim", "nourriture"},
        "prayer_room": {"prayer", "pray", "mosque", "oración", "oracion", "orar", "prière", "prier"},
        "sensory_room": {"sensory", "quiet room", "autism", "sensorial", "sensoriel", "salle calme"},
        "info_desk": {"info desk", "information desk", "help desk", "información", "informacion", "renseignements", "accueil"},
        "atm": {"atm", "cash machine", "cajero", "efectivo", "distributeur", "espèces"},
        "charging": {"charging", "charge my phone", "cargar el teléfono", "cargar mi", "recharger"},
    }.items()
}

_ACCESSIBLE = _compile({
    "wheelchair", "accessible", "step-free", "step free", "elevator", "lift", "ramp",
    "silla de ruedas", "accesible", "ascensor", "rampa", "sin escaleras",
    "fauteuil roulant", "ascenseur", "rampe", "sans marches", "mobility",
})
_NAV = _compile({
    "how do i get", "how to get", "how can i get", "way to", "route", "take me",
    "navigate", "get to", "go to", "going to", "where is", "where's", "fastest",
    "cómo llego", "como llego", "llegar a", "dónde está", "donde esta", "ir a",
    "comment aller", "aller à", "aller a", "où est", "ou est", "itinéraire", "chemin",
})
_CROWD = _compile({
    "crowd", "busy", "busiest", "queue", "line at", "wait time", "congest", "packed",
    "lleno", "fila", "cola", "cuánta gente", "cuanta gente", "monde", "foule",
    "attente", "bondé", "bonde",
})
_TRANSPORT = _compile({
    "metro", "subway", "train", "rail", "bus", "shuttle", "parking", "taxi", "uber",
    "ferry", "get home", "leave the stadium", "get to the stadium", "reach the stadium",
    "transporte", "tren", "autobús", "autobus", "estacionamiento", "cómo salgo",
    "transport", "navette", "stationnement", "rentrer", "y aller",
})
_MATCH = _compile({
    "match", "game", "kickoff", "kick-off", "kick off", "fixture", "final", "who plays",
    "what time", "partido", "juego", "a qué hora", "a que hora", "coup d'envoi",
    "heure du match", "quel match",
})
_SUSTAIN = _compile({
    "recycl", "sustain", "environment", "reciclaje", "sostenib", "recyclage",
    "durable", "écolo", "ecolo", "compost",
})
_GREET = re.compile(r"\b(hi|hello|hey|hola|buenas|bonjour|salut)\b|good (morning|afternoon|evening)")

INTENTS = (
    "greeting", "navigation", "facility", "crowd", "transport",
    "match", "accessibility", "sustainability", "general",
)


def detect_language(text: str, requested: str = "auto") -> str:
    """Pick the reply language: explicit user choice wins, else a marker score."""
    if requested in LANGUAGES:
        return requested
    lowered = text.lower()
    words = set(re.findall(r"[\w'áéíóúüñàâçèéêîôûœ-]+", lowered))

    def score(markers: list[str], chars: set[str]) -> int:
        hits = 0
        for marker in markers:
            if " " in marker or "'" in marker:
                if marker in lowered:
                    hits += 1
            elif marker in words:
                hits += 1
        if chars & set(lowered):
            hits += 2
        return hits

    es, fr = score(_ES_MARKERS, _ES_CHARS), score(_FR_MARKERS, _FR_CHARS)
    if max(es, fr) == 0:
        return "en"
    return "es" if es >= fr else "fr"


def facility_type_from_text(text: str) -> str | None:
    lowered = text.lower()
    for ftype, pattern in _FACILITY_PATTERNS.items():
        if pattern.search(lowered):
            return ftype
    return None


def wants_accessible(text: str) -> bool:
    return bool(_ACCESSIBLE.search(text.lower()))


def classify_intent(text: str, facility_type: str | None, zone_mentions: int) -> str:
    """Ordered rules: the most specific signal wins; greeting only fires when
    nothing else matched, so 'Hola, ¿dónde está la Puerta A?' is navigation."""
    lowered = text.lower()
    if facility_type:
        return "facility"
    if _NAV.search(lowered) and zone_mentions > 0:
        return "navigation"
    if zone_mentions >= 2:
        return "navigation"
    if _CROWD.search(lowered):
        return "crowd"
    if _TRANSPORT.search(lowered):
        return "transport"
    if _MATCH.search(lowered):
        return "match"
    if wants_accessible(lowered):
        return "accessibility"
    if _SUSTAIN.search(lowered):
        return "sustainability"
    if _NAV.search(lowered):
        return "navigation"
    if len(lowered) <= 60 and _GREET.search(lowered):
        return "greeting"
    return "general"
