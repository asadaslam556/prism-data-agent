"""Ask the configured endpoint which models it actually serves.

Gateways rename things. A model called "claude-haiku-4-5" on one endpoint might
be "claude-haiku-4-5@default" on another, or simply not be there at all, and a
404 telling you the model doesn't exist is not much help on its own when you
can't see the list.

Run it from the backend folder with the venv active:

    python list_models.py

It reads the same .env the app does, so whatever it prints is what LLM_MODEL
can be set to. Nothing is written or changed -- it only reads.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.agent import providers  # noqa: E402
from app.config import settings  # noqa: E402


def endpoint_and_key() -> tuple[str, str, str]:
    """Where to ask, and what to authenticate with, for the active provider."""
    provider = providers.active_provider()

    if provider == "anthropic":
        base = settings.anthropic_base_url or os.environ.get("ANTHROPIC_BASE_URL")
        key = settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not base:
            raise SystemExit(
                "LLM_PROVIDER=anthropic with no gateway configured, so the model list "
                "is Anthropic's public one: https://docs.anthropic.com/en/docs/about-claude/models"
            )
        return base.rstrip("/") + "/v1/models", key, provider

    if provider == "openai":
        base = settings.openai_base_url or os.environ.get("OPENAI_BASE_URL")
        key = settings.openai_api_key or os.environ.get("OPENAI_API_KEY", "")
        if not base:
            base = "https://api.openai.com/v1"
        return base.rstrip("/") + "/models", key, provider

    raise SystemExit(
        f"LLM_PROVIDER={provider} doesn't have a model list endpoint. "
        "For ollama, run `ollama list` instead."
    )


def fetch(url: str, key: str) -> dict:
    request = urllib.request.Request(url)
    # Gateways vary: some want the Anthropic header, some the OpenAI one.
    # Sending both is harmless and saves a round of guessing.
    request.add_header("Authorization", f"Bearer {key}")
    request.add_header("x-api-key", key)
    request.add_header("anthropic-version", "2023-06-01")
    request.add_header("Accept", "application/json")

    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode())


def model_names(payload: dict) -> list[str]:
    """Pull model ids out of whichever response shape came back.

    Three shapes in the wild so far: OpenAI's {"data": [{"id": ...}]}, a plain
    {"models": [...]} list, and gateways that publish a catalogue grouped by
    API family. The last one nests the names a couple of levels down and broke
    the first version of this, so the walk below just recurses and collects
    anything that looks like a model id wherever it turns up.
    """
    found: list[str] = []

    def walk(node) -> None:
        if isinstance(node, str):
            found.append(node)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            for key in ("id", "name", "model"):
                value = node.get(key)
                if isinstance(value, str):
                    found.append(value)
                    return
            for key in ("data", "models", "catalog", "catalogue"):
                if key in node:
                    walk(node[key])

    walk(payload)
    # keep insertion order, drop repeats
    return list(dict.fromkeys(found))


def groups(payload: dict) -> list[tuple[str, list[str]]]:
    """Gateways that group models by API family: keep that grouping.

    It matters here -- an Anthropic-family name only works with
    LLM_PROVIDER=anthropic, an OpenAI one only with LLM_PROVIDER=openai. Showing
    them in one flat list would invite picking a name the active provider can't
    actually call.
    """
    catalog = payload.get("catalog") or payload.get("catalogue")
    if not isinstance(catalog, list):
        return []
    out = []
    for entry in catalog:
        if not isinstance(entry, dict):
            continue
        label = str(entry.get("tool") or entry.get("name") or entry.get("base_path") or "models")
        names = [m for m in entry.get("models", []) if isinstance(m, str)]
        if names:
            out.append((label, names))
    return out


def matches_provider(label: str, provider: str) -> bool:
    return provider.lower() in label.lower()


def main() -> int:
    url, key, provider = endpoint_and_key()
    print(f"provider : {provider}")
    print(f"asking   : {url}")
    print(f"key      : {'set (' + str(len(key)) + ' chars)' if key else 'MISSING'}")
    print()

    try:
        payload = fetch(url, key)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:400]
        print(f"HTTP {exc.code} from the endpoint.")
        if exc.code in (401, 403):
            print("That's an auth failure -- the key is wrong, expired, or not valid here.")
        elif exc.code == 404:
            print("This endpoint has no model-list route. Ask whoever runs the gateway")
            print("for the list, or check its own documentation.")
        print(f"\n{body}")
        return 1
    except Exception as exc:
        print(f"Could not reach it: {type(exc).__name__}: {exc}")
        print("Check the base URL, and whether you need to be on a VPN.")
        return 1

    grouped = groups(payload)
    names = model_names(payload)

    if not names:
        print("Reached it, but no model names were recognisable in the reply:")
        print(json.dumps(payload, indent=2)[:1500])
        return 1

    current = providers.active_model()

    if grouped:
        # This gateway groups by API family, and only one of those families is
        # reachable with the provider currently configured.
        mine = [(label, models) for label, models in grouped if matches_provider(label, provider)]
        others = [(label, models) for label, models in grouped if not matches_provider(label, provider)]

        if mine:
            print(f"Models you can use right now (LLM_PROVIDER={provider}):\n")
            for _, models in mine:
                for name in models:
                    print(f"  {name}")
            usable = [n for _, models in mine for n in models]
        else:
            print(f"Nothing here matches LLM_PROVIDER={provider}. Listing everything:\n")
            usable = names

        if others:
            print("\nAlso on this gateway, but you would need to switch LLM_PROVIDER:")
            for label, models in others:
                print(f"  [{label}] {', '.join(models[:4])}" + (" ..." if len(models) > 4 else ""))
    else:
        print(f"{len(names)} model(s) available. Set LLM_MODEL to one of these:\n")
        for name in sorted(names):
            print(f"  {name}")
        usable = names

    print()
    if current in usable:
        print(f"Your current LLM_MODEL ({current}) is on the list -- that part is fine.")
        return 0

    print(f"Your current LLM_MODEL ({current}) is NOT usable with this provider.")
    stem = current.split("@")[0].lower()
    close = [n for n in usable if stem and stem in n.lower()]
    if close:
        print("\nDid you mean:")
        for name in close:
            print(f"  LLM_MODEL={name}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
