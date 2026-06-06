import os

from evals.ragas import runner


def test_build_embeddings_returns_langchain_compatible_wrapper(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    embeddings = runner._build_embeddings()

    assert hasattr(embeddings, "embed_query")
    assert hasattr(embeddings, "embed_documents")
