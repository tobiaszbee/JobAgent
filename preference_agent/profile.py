_DISTILL_TOOL = {
    "name": "submit_profile",
    "description": "Submit the distilled preference profile as structured signals.",
    "input_schema": {
        "type": "object",
        "properties": {
            "signals": {
                "type": "array",
                "description": "One signal per dimension or distinct value.",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["ACCEPT", "REJECT", "INFER", "NEUTRAL"],
                        },
                        "dim": {
                            "type": "string",
                            "description": "Dimension name from the allowed list.",
                        },
                        "value": {
                            "type": "string",
                            "description": "Sub-value (e.g. product_saas, agency_outsourcing).",
                        },
                        "conf": {
                            "type": "string",
                            "enum": ["ABSOLUTE", "HIGH", "MEDIUM", "LOW"],
                            "description": "Confidence level for ACCEPT/REJECT signals.",
                        },
                        "n_match": {
                            "type": "integer",
                            "description": "X in n=X/Y, jobs matching this signal.",
                        },
                        "n_total": {
                            "type": "integer",
                            "description": "Y in n=X/Y for ACCEPT/REJECT; evidence count for INFER.",
                        },
                        "note": {
                            "type": "string",
                            "description": "User reason or additional context.",
                        },
                    },
                    "required": ["type", "dim"],
                },
            }
        },
        "required": ["signals"],
    },
}


def render_signals(signals: list[dict]) -> str:
    """Render structured signals to the text format consumed by the scorer prompt."""
    lines = []
    for s in signals:
        t = s["type"]
        dim = s.get("dim", "")
        value = s.get("value")
        conf = s.get("conf")
        n_match = s.get("n_match")
        n_total = s.get("n_total")
        note = s.get("note")

        if t in ("ACCEPT", "REJECT"):
            inner = [f"{dim}={value}" if value else dim]
            if conf:
                inner.append(f"conf={conf}")
            if n_match is not None and n_total is not None:
                inner.append(f"n={n_match}/{n_total}")
            line = f"{t}[{'; '.join(inner)}]"
            if note:
                line += f": {note}"
        elif t == "INFER":
            inner_str = f"{dim}={value}" if value else dim
            if n_total is not None:
                inner_str += f"; from={n_total} examples"
            line = f"INFER[{inner_str}]"
            if note:
                line += f": {note}"
        elif t == "NEUTRAL":
            line = f"NEUTRAL[{dim}; no_signal]"
        else:
            raise ValueError(f"Unknown signal type: {t!r}")

        lines.append(line)
    return "\n".join(lines)
