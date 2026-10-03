"""Native LangChain clients for the local subscription transports."""


def create_model(provider: str, model: str, *, base_url: str | None = None, **kwargs):
    """Create a client with a concrete model ID; kwargs go to LangChain."""
    if provider == "codex":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model,
            base_url=base_url or "http://127.0.0.1:8000/v1",
            api_key="local-proxy",
            use_responses_api=True,
            store=False,
            **kwargs,
        )
    if provider == "claude":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=model,
            base_url=base_url or "http://127.0.0.1:8001",
            api_key="local-proxy",
            **kwargs,
        )
    raise ValueError(f"Unsupported provider: {provider}")
