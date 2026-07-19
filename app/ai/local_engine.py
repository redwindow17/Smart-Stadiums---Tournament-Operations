"""Offline assistant engine.

A deterministic, template-based generator over the same grounded context the
Claude engine receives. It exists so that:

* the app runs (and can be graded) with **zero** external accounts or network,
* every AI outage degrades gracefully instead of failing the user,
* behaviour is unit-testable.

Templates ship in the three host-country languages (en / es / fr).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

PHRASES: Dict[str, Dict[str, Any]] = {
    "en": {
        "greeting": "Hi! I'm StadiumIQ, your matchday assistant at {venue}. Ask me about routes, facilities, transport, crowd levels, accessibility or today's match.",
        "acc_word": "step-free ",
        "route_intro": "Fastest {acc}route to {dest} (about {mins} min):",
        "route_start": "Start at {name}",
        "route_walk": "Walk to {name} (~{mins} min)",
        "route_none": "I couldn't find a {acc}route between those points. Try naming a gate or concourse, like 'Gate A'.",
        "route_need_dest": "Tell me where you'd like to go - for example 'How do I get to Gate C?'",
        "crowd_hint": "Heads up: {busiest} is busiest right now ({busiest_pct}%); {quietest} is quieter ({quietest_pct}%).",
        "facility_intro": "Nearest {ftype} from {origin}:",
        "facility_line": "{name} - about {mins} min walk",
        "facility_none": "I couldn't find that facility here - the team at the Info Desk can help you.",
        "crowd_report": "Current status at {venue} ({phase}): busiest gate is {busiest} at {busiest_pct}%, quietest is {quietest} at {quietest_pct}%.",
        "crowd_tip": "Tip: use {quietest} to save queue time.",
        "phases": {"ingress": "fans arriving", "in_match": "match in progress", "egress": "fans leaving", "quiet": "quiet period"},
        "transport_intro": "Getting to and from {venue}:",
        "match_upcoming": "Next match at {venue}: {stage} - {home} vs {away}. Kickoff: {kickoff}.",
        "match_live": "Happening right now at {venue}: {stage} - {home} vs {away} (kickoff was {kickoff}).",
        "match_none": "There are no more matches scheduled at {venue} in the tournament fixture list.",
        "accessibility_intro": "Accessibility at {venue}:",
        "sustainability_intro": "Sustainability at {venue}:",
        "general": "I can help with routes inside {venue}, facilities (restrooms, water refill, first aid...), transport, crowd levels, accessibility and match info. What do you need?",
        "medical_note": "If this is an emergency, alert the nearest steward immediately.",
        "ftypes": {
            "restroom": "restroom", "accessible_restroom": "accessible restroom",
            "water_refill": "water refill station", "first_aid": "first-aid point",
            "food": "food outlet", "prayer_room": "prayer room", "sensory_room": "sensory room",
            "info_desk": "info desk", "atm": "ATM", "charging": "charging station",
        },
    },
    "es": {
        "greeting": "¡Hola! Soy StadiumIQ, tu asistente en {venue}. Pregúntame por rutas, servicios, transporte, aglomeraciones, accesibilidad o el partido de hoy.",
        "acc_word": "sin escaleras ",
        "route_intro": "Ruta más rápida {acc}hasta {dest} (unos {mins} min):",
        "route_start": "Empieza en {name}",
        "route_walk": "Camina hasta {name} (~{mins} min)",
        "route_none": "No encontré una ruta {acc}entre esos puntos. Prueba con el nombre de una puerta o explanada, por ejemplo 'Puerta A'.",
        "route_need_dest": "Dime a dónde quieres ir; por ejemplo: '¿Cómo llego a la Puerta C?'",
        "crowd_hint": "Atención: {busiest} es la más concurrida ahora ({busiest_pct}%); {quietest} está más despejada ({quietest_pct}%).",
        "facility_intro": "{ftype} más cercano desde {origin}:",
        "facility_line": "{name} - a unos {mins} min a pie",
        "facility_none": "No encontré ese servicio aquí; el personal del punto de información puede ayudarte.",
        "crowd_report": "Situación actual en {venue} ({phase}): la puerta más concurrida es {busiest} con {busiest_pct}%, la más despejada es {quietest} con {quietest_pct}%.",
        "crowd_tip": "Consejo: usa {quietest} para ahorrar tiempo de fila.",
        "phases": {"ingress": "llegada de aficionados", "in_match": "partido en curso", "egress": "salida de aficionados", "quiet": "periodo tranquilo"},
        "transport_intro": "Cómo llegar y salir de {venue}:",
        "match_upcoming": "Próximo partido en {venue}: {stage} - {home} vs {away}. Inicio: {kickoff}.",
        "match_live": "Ahora mismo en {venue}: {stage} - {home} vs {away} (comenzó a las {kickoff}).",
        "match_none": "No hay más partidos programados en {venue} en el calendario del torneo.",
        "accessibility_intro": "Accesibilidad en {venue}:",
        "sustainability_intro": "Sostenibilidad en {venue}:",
        "general": "Puedo ayudarte con rutas dentro de {venue}, servicios (baños, agua, primeros auxilios...), transporte, aglomeraciones, accesibilidad e información del partido. ¿Qué necesitas?",
        "medical_note": "Si es una emergencia, avisa de inmediato al personal más cercano.",
        "ftypes": {
            "restroom": "baño", "accessible_restroom": "baño accesible",
            "water_refill": "punto de recarga de agua", "first_aid": "puesto de primeros auxilios",
            "food": "punto de comida", "prayer_room": "sala de oración", "sensory_room": "sala sensorial",
            "info_desk": "punto de información", "atm": "cajero automático", "charging": "estación de carga",
        },
    },
    "fr": {
        "greeting": "Bonjour ! Je suis StadiumIQ, votre assistant au {venue}. Demandez-moi des itinéraires, des services, les transports, l'affluence, l'accessibilité ou le match du jour.",
        "acc_word": "sans marches ",
        "route_intro": "Itinéraire le plus rapide {acc}vers {dest} (environ {mins} min) :",
        "route_start": "Départ : {name}",
        "route_walk": "Marchez jusqu'à {name} (~{mins} min)",
        "route_none": "Je n'ai pas trouvé d'itinéraire {acc}entre ces points. Essayez le nom d'une porte ou d'une esplanade, par exemple « Porte A ».",
        "route_need_dest": "Dites-moi où vous voulez aller, par exemple : « Comment aller à la Porte C ? »",
        "crowd_hint": "Attention : {busiest} est la plus fréquentée en ce moment ({busiest_pct}%) ; {quietest} est plus calme ({quietest_pct}%).",
        "facility_intro": "{ftype} le plus proche depuis {origin} :",
        "facility_line": "{name} - à environ {mins} min à pied",
        "facility_none": "Je n'ai pas trouvé ce service ici ; le personnel du point d'information peut vous aider.",
        "crowd_report": "Situation actuelle au {venue} ({phase}) : porte la plus fréquentée {busiest} à {busiest_pct}%, la plus calme {quietest} à {quietest_pct}%.",
        "crowd_tip": "Conseil : passez par {quietest} pour gagner du temps.",
        "phases": {"ingress": "arrivée des supporters", "in_match": "match en cours", "egress": "sortie des supporters", "quiet": "période calme"},
        "transport_intro": "Pour rejoindre ou quitter {venue} :",
        "match_upcoming": "Prochain match au {venue} : {stage} - {home} vs {away}. Coup d'envoi : {kickoff}.",
        "match_live": "En ce moment au {venue} : {stage} - {home} vs {away} (coup d'envoi : {kickoff}).",
        "match_none": "Aucun autre match n'est programmé au {venue} dans le calendrier du tournoi.",
        "accessibility_intro": "Accessibilité au {venue} :",
        "sustainability_intro": "Développement durable au {venue} :",
        "general": "Je peux vous aider : itinéraires dans {venue}, services (toilettes, eau, premiers secours...), transports, affluence, accessibilité et infos match. Que cherchez-vous ?",
        "medical_note": "En cas d'urgence, alertez immédiatement le steward le plus proche.",
        "ftypes": {
            "restroom": "toilettes", "accessible_restroom": "toilettes accessibles",
            "water_refill": "point d'eau", "first_aid": "poste de premiers secours",
            "food": "point de restauration", "prayer_room": "salle de prière", "sensory_room": "salle sensorielle",
            "info_desk": "point d'information", "atm": "distributeur", "charging": "station de recharge",
        },
    },
}


class LocalEngine:
    """Deterministic template renderer over the grounded context."""

    name = "local"

    def generate(
        self,
        message: str,
        context: Dict[str, Any],
        history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        lang = context.get("language", "en")
        phrases = PHRASES.get(lang, PHRASES["en"])
        intent = context.get("intent", "general")
        venue_name = context.get("venue", {}).get("name", "the stadium")
        handler = getattr(self, f"_{intent}", None)
        if handler is None:
            return phrases["general"].format(venue=venue_name)
        return handler(context, phrases, venue_name)

    # --- intent renderers -------------------------------------------------

    def _greeting(self, ctx, p, venue) -> str:
        return p["greeting"].format(venue=venue)

    def _general(self, ctx, p, venue) -> str:
        return p["general"].format(venue=venue)

    def _navigation(self, ctx, p, venue) -> str:
        route = ctx.get("route")
        acc = p["acc_word"] if ctx.get("accessible") else ""
        if not ctx.get("route_requested"):
            return p["route_need_dest"]
        if not route:
            return p["route_none"].format(acc=acc)
        dest = route["steps"][-1]["zone_name"] if route["steps"] else route["destination"]
        lines = [p["route_intro"].format(acc=acc, dest=dest, mins=route["total_minutes"])]
        for i, step in enumerate(route["steps"]):
            if i == 0:
                lines.append("- " + p["route_start"].format(name=step["zone_name"]))
            else:
                lines.append("- " + p["route_walk"].format(name=step["zone_name"], mins=step["minutes"]))
        hint = self._crowd_hint(ctx, p)
        if hint:
            lines.append(hint)
        return "\n".join(lines)

    def _facility(self, ctx, p, venue) -> str:
        facilities = ctx.get("facilities") or []
        if not facilities:
            return p["facility_none"]
        ftype = ctx.get("facility_type", "info_desk")
        label = p["ftypes"].get(ftype, ftype)
        origin = ctx.get("origin_name", venue)
        lines = [p["facility_intro"].format(ftype=label, origin=origin)]
        for fac in facilities:
            lines.append("- " + p["facility_line"].format(name=fac["name"], mins=fac["minutes"]))
        if ftype == "first_aid":
            lines.append(p["medical_note"])
        return "\n".join(lines)

    def _crowd(self, ctx, p, venue) -> str:
        crowd = ctx.get("crowd")
        if not crowd:
            return p["general"].format(venue=venue)
        phase = p["phases"].get(crowd["phase"], crowd["phase"])
        text = p["crowd_report"].format(
            venue=venue,
            phase=phase,
            busiest=crowd["busiest"]["name"],
            busiest_pct=crowd["busiest"]["pct"],
            quietest=crowd["quietest"]["name"],
            quietest_pct=crowd["quietest"]["pct"],
        )
        return text + "\n" + p["crowd_tip"].format(quietest=crowd["quietest"]["name"])

    def _transport(self, ctx, p, venue) -> str:
        options = ctx.get("transport") or []
        lines = [p["transport_intro"].format(venue=venue)]
        for opt in options:
            lines.append(f"- {opt['name']}: {opt['detail']}")
        return "\n".join(lines)

    def _match(self, ctx, p, venue) -> str:
        match = ctx.get("match")
        if not match:
            return p["match_none"].format(venue=venue)
        key = "match_live" if match.get("status") == "live" else "match_upcoming"
        return p[key].format(
            venue=venue, stage=match["stage"], home=match["home"], away=match["away"], kickoff=match["kickoff"]
        )

    def _accessibility(self, ctx, p, venue) -> str:
        info = ctx.get("accessibility") or {}
        lines = [p["accessibility_intro"].format(venue=venue)]
        if info.get("summary"):
            lines.append(info["summary"])
        for feature in info.get("features", []):
            lines.append(f"- {feature}")
        return "\n".join(lines)

    def _sustainability(self, ctx, p, venue) -> str:
        tips = ctx.get("sustainability") or []
        lines = [p["sustainability_intro"].format(venue=venue)]
        for tip in tips:
            lines.append(f"- {tip}")
        return "\n".join(lines)

    # --- helpers ----------------------------------------------------------

    @staticmethod
    def _crowd_hint(ctx, p) -> str:
        crowd = ctx.get("crowd")
        if not crowd or crowd["busiest"]["pct"] < 60:
            return ""
        return p["crowd_hint"].format(
            busiest=crowd["busiest"]["name"],
            busiest_pct=crowd["busiest"]["pct"],
            quietest=crowd["quietest"]["name"],
            quietest_pct=crowd["quietest"]["pct"],
        )

    def ops_brief(self, snapshot: Dict[str, Any], recommendations: List[Dict[str, str]]) -> str:
        hot = [z for z in snapshot["zones"] if z["level"] in ("high", "critical")]
        head = (
            f"Phase: {snapshot['phase']}. {len(hot)} zone(s) above comfortable density "
            f"out of {len(snapshot['zones'])} monitored."
        )
        lines = [head] + [f"- [{r['priority']}] {r['action']} ({r['reason']})" for r in recommendations]
        return "\n".join(lines)
