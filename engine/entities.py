"""Canonical entity registry: one row per company, its ecosystem group, ticker, and name aliases.

Aliases are matched as whole tokens against site `developer`/`tenant` fields (split on | ; ,)
and against agreement `parties` (split on /). Anything unmatched falls into group "Other".
"""

# group -> list of (canonical, ticker or None if private, [aliases])
REGISTRY = {
    "Hyperscaler": [
        ("Microsoft", "MSFT", ["Microsoft", "Microsoft Corporation", "Azure"]),
        ("Amazon", "AMZN", ["Amazon", "AWS", "Amazon Web Services", "Amazon.com", "Amazon/AWS"]),
        ("Alphabet", "GOOGL", ["Google", "Alphabet", "Google Cloud", "Google LLC"]),
        ("Meta", "META", ["Meta", "Meta (FKA Facebook)", "Meta Platforms", "Facebook"]),
        ("Oracle", "ORCL", ["Oracle", "Oracle Cloud", "OCI"]),
    ],
    "Frontier lab": [
        ("OpenAI", None, ["OpenAI", "Stargate"]),
        ("Anthropic", None, ["Anthropic"]),
        ("xAI", None, ["xAI", "X.AI", "SpaceX", "SpaceXSI"]),  # xAI merged into SpaceX in the deal data
        ("Reflection AI", None, ["Reflection AI"]),
        ("Poolside", None, ["Poolside"]),
    ],
    "Neocloud": [
        ("CoreWeave", "CRWV", ["CoreWeave"]),
        ("Nebius", "NBIS", ["Nebius"]),
        ("Lambda", None, ["Lambda"]),
        ("Crusoe", None, ["Crusoe"]),
        ("Nscale", None, ["Nscale", "Nscale Global"]),
        ("Fluidstack", None, ["Fluidstack"]),
        ("Together AI", None, ["Together AI"]),
        ("TensorWave", None, ["TensorWave"]),
        ("Vultr", None, ["Vultr"]),
        ("Voltage Park", None, ["Voltage Park"]),
        ("RunPod", None, ["RunPod"]),
    ],
    "Miner-turned-AI host": [
        ("Applied Digital", "APLD", ["Applied Digital"]),
        ("IREN", "IREN", ["IREN", "IREN (f.k.a. Iris Energy)", "Iris Energy"]),
        ("TeraWulf", "WULF", ["TeraWulf"]),
        ("Cipher Mining", "CIFR", ["Cipher Mining", "Cipher Mining Technologies", "Cipher"]),
        ("Hut 8", "HUT", ["Hut 8"]),
        ("Core Scientific", "CORZ", ["Core Scientific", "Core Scientific Holdings"]),
        ("Riot Platforms", "RIOT", ["Riot Platforms", "Riot"]),
        ("Galaxy Digital", "GLXY", ["Galaxy Digital", "Galaxy"]),
    ],
    "Chips & hardware": [
        ("NVIDIA", "NVDA", ["NVIDIA", "NVIDIA Corporation"]),
        ("AMD", "AMD", ["AMD", "AMD Ventures"]),
        ("Broadcom", "AVGO", ["Broadcom"]),
        ("TSMC", "TSM", ["TSMC"]),
        ("Micron", "MU", ["Micron"]),
        ("Dell", "DELL", ["Dell"]),
        ("Supermicro", "SMCI", ["Supermicro"]),
        ("Cisco", "CSCO", ["Cisco"]),
        ("Nokia", "NOK", ["Nokia"]),
    ],
    "Developer / landlord": [
        ("Digital Realty", "DLR", ["Digital Realty"]),
        ("QTS (Blackstone)", None, ["QTS", "QTS Data Centers"]),
        ("Vantage Data Centers", None, ["Vantage Data Centers", "Vantage"]),
        ("Related Digital", None, ["Related Digital"]),
        ("Tract", None, ["Tract", "Tract Infra"]),
        ("Cloverleaf", None, ["Cloverleaf Infrastructure", "Cloverleaf"]),
        ("Stack Infrastructure", None, ["Stack Infrastructure"]),
        ("Aligned Data Centers", None, ["Aligned Data Centers", "Aligned"]),
        ("CyrusOne", None, ["CyrusOne"]),
        ("Equinix", "EQIX", ["Equinix"]),
    ],
    "Capital provider": [
        ("SoftBank", "SFTBY", ["SoftBank Group", "SoftBank"]),
        ("Blackstone", "BX", ["Blackstone", "Blackstone Credit & Insurance"]),
        ("Blue Owl", "OWL", ["Blue Owl"]),
        ("Brookfield", "BN", ["Brookfield"]),
        ("JPMorgan", "JPM", ["JPMorgan", "JPMorgan Chase"]),
        ("Morgan Stanley", "MS", ["Morgan Stanley"]),
        ("Goldman Sachs", "GS", ["Goldman Sachs"]),
        ("Citi", "C", ["Citi", "Citibank", "Citigroup"]),
        ("MUFG", "MUFG", ["MUFG"]),
        ("Wells Fargo", "WFC", ["Wells Fargo"]),
        ("MGX", None, ["MGX"]),
        ("Mubadala", None, ["Mubadala Capital", "Mubadala"]),
    ],
    "Power": [
        ("Constellation", "CEG", ["Constellation Energy", "Constellation"]),
        ("Vistra", "VST", ["Vistra"]),
        ("AEP", "AEP", ["AEP", "AEP Ohio"]),
        ("SB Energy", None, ["SB Energy"]),
        ("NRG", "NRG", ["NRG"]),
        ("Talen", "TLN", ["Talen Energy", "Talen"]),
    ],
}

ALIAS = {}
META = {}
for group, rows in REGISTRY.items():
    for canon, ticker, aliases in rows:
        META[canon] = {"group": group, "ticker": ticker, "public": ticker is not None}
        for a in aliases + [canon]:
            ALIAS[a.strip().lower()] = canon


def canon(name: str):
    """Map a raw party/developer string to a canonical entity, or None."""
    if not isinstance(name, str):
        return None
    return ALIAS.get(name.strip().lower())
