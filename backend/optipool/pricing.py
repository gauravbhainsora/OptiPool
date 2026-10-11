def cost(pricing, nodes):
    if not pricing or not pricing.get("components"):
        return {"available": False, "reason": "No verified matching prices in this saved snapshot"}
    components = pricing["components"]
    if any(c.get("on_demand_hourly") is None for c in components):
        return {"available": False, "reason": "A required component price is missing"}
    demand = sum(c["on_demand_hourly"] for c in components) * nodes
    cud_available = all(not c.get("cud_eligible") or c.get("cud_3y_hourly") is not None for c in components)
    cud = (
        sum(c["cud_3y_hourly"] if c.get("cud_eligible") else c["on_demand_hourly"] for c in components)
        * nodes
        if cud_available
        else None
    )
    obligation = sum(c.get("cud_3y_hourly", 0) or 0 for c in components if c.get("cud_eligible")) * nodes
    return {
        "available": True,
        "currency": "USD",
        "on_demand_hourly": demand,
        "on_demand_monthly": demand * 730,
        "cud_3y_hourly": cud,
        "cud_3y_monthly": cud * 730 if cud is not None else None,
        "commitment_3y_obligation": obligation * 24 * 365 * 3 if cud_available else None,
        "source": pricing["source"],
        "saved_at": pricing["saved_at"],
        "synthetic": pricing.get("synthetic", False),
        "components": components,
        "assumption": "Hypothetical new 3-year resource-based commitment fully covering eligible resources; "
        "730-hour months. Existing CUD coverage, tax, credits and actual bills are not modeled.",
    }
