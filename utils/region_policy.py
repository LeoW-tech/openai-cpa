OPENAI_BLOCKED_REGIONS = {"CN"}


def is_openai_region_blocked(loc: str | None) -> bool:
    if not loc:
        return False
    return str(loc).strip().upper() in OPENAI_BLOCKED_REGIONS
