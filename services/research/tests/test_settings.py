import pytest

from auspex_research.settings import ResearchSettings, load_settings


def test_defaults_and_derived_policy() -> None:
    settings = load_settings({"PATH": "/bin"})
    assert settings == ResearchSettings()
    assert settings.retry_policy().timeout_s == 8.0 and settings.retry_policy().max_attempts == 3


def test_env_overrides_are_parsed_and_validated() -> None:
    settings = load_settings(
        {
            "AUSPEX_RESEARCH_MAX_ATTEMPTS": "2",
            "AUSPEX_RESEARCH_READ_TIMEOUT_S": "1.5",
            "AUSPEX_RESEARCH_POLYMARKET_US_BASE_URL": "https://gateway.test/",
        }
    )
    assert (settings.max_attempts, settings.read_timeout_s) == (2, 1.5)
    assert settings.polymarket_us_base_url == "https://gateway.test"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("MAX_ATTEMPTS", "9"),
        ("READ_TIMEOUT_S", "0"),
        ("CONNECT_TIMEOUT_S", "abc"),
        ("MAX_CONCURRENCY", "0"),
        ("POLYMARKET_US_BASE_URL", "http://gateway.test"),
        ("POLYMARKET_US_BASE_URL", "https://user:hunter2@gateway.test"),
        ("POLYMARKET_US_BASE_URL", "https://gateway.test/?token=hunter2"),
        ("MAX_ATEMPTS", "3"),  # typo must not silently use the default
    ],
)
def test_invalid_settings_fail_without_echoing_values(name: str, value: str) -> None:
    with pytest.raises(ValueError, match="invalid research settings") as err:
        load_settings({f"AUSPEX_RESEARCH_{name}": value})
    assert "hunter2" not in str(err.value) and value not in str(err.value)
