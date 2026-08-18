def test_provider_package_exports_registry():
    from providers import PROVIDERS, create_provider, get_provider_names

    assert "ollama" in PROVIDERS
    assert "openai" in PROVIDERS
    assert callable(create_provider)
    assert set(get_provider_names()) == set(PROVIDERS)
