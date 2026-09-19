"""Tests for the model-listing helper.

The first version of list_models.py only understood two response shapes and
printed a raw JSON dump when it met a third -- a gateway that publishes its
catalogue grouped by API family. The payload below is the real reply from one
of those, so the parser stays honest.
"""
from __future__ import annotations

import list_models

GROUPED_CATALOGUE = {
    "service": "Example LLM Gateway",
    "documentation": "https://gateway.example/docs/",
    "catalog": [
        {
            "tool": "CURL / Gemini",
            "base_path": "/v1beta",
            "models": ["google/gemini-2.5-flash", "google/gemini-2.5-pro"],
        },
        {
            "tool": "CURL / OpenAI",
            "base_path": "/v1/chat/completions",
            "models": ["gpt-5", "gpt-5-mini"],
        },
        {
            "tool": "CURL / Mistral",
            "base_path": "/v1/mistral",
            "models": [
                "mistral-large@2411",
                "mistral-small@2503",
                "codestral@default",
            ],
        },
    ],
}


def test_grouped_catalogue_is_parsed():
    names = list_models.model_names(GROUPED_CATALOGUE)
    assert "mistral-small@2503" in names
    assert "gpt-5" in names
    assert len(names) == 7


def test_openai_shape_is_parsed():
    payload = {"data": [{"id": "gpt-4o-mini"}, {"id": "gpt-4o"}]}
    assert list_models.model_names(payload) == ["gpt-4o-mini", "gpt-4o"]


def test_plain_list_shape_is_parsed():
    payload = {"models": ["llama3.1", "qwen2.5"]}
    assert list_models.model_names(payload) == ["llama3.1", "qwen2.5"]


def test_duplicates_are_dropped_and_order_kept():
    payload = {"models": ["a", "b", "a"]}
    assert list_models.model_names(payload) == ["a", "b"]


def test_groups_keeps_the_api_families_apart():
    grouped = list_models.groups(GROUPED_CATALOGUE)
    labels = [label for label, _ in grouped]
    assert labels == ["CURL / Gemini", "CURL / OpenAI", "CURL / Mistral"]


def test_groups_is_empty_for_ungrouped_payloads():
    assert list_models.groups({"data": [{"id": "gpt-4o"}]}) == []


def test_provider_matching_picks_the_right_family():
    """A name only works with the provider that speaks its API, so the script
    must not offer Gemini names to someone running LLM_PROVIDER=openai."""
    assert list_models.matches_provider("CURL / OpenAI", "openai")
    assert not list_models.matches_provider("CURL / Gemini", "openai")
    assert not list_models.matches_provider("CURL / Mistral", "openai")
