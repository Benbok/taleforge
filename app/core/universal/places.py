"""Public naming for an entry placeholder, without altering authored world data."""

START_LOCATION_NAME = "Начальная локация"


def public_location_name(campaign, location, name=None):
    candidate = location.name if name is None else name
    if (
        campaign.ruleset_id == "universal"
        and location.kind == "location"
        and (location.state or {}).get("studio_entry")
        and candidate == campaign.name
    ):
        return START_LOCATION_NAME
    return candidate
