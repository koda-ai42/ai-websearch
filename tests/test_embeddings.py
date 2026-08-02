from ai_websearch.embeddings import _model_dimension


def test_embedding_dimension_prefers_current_api() -> None:
    class Model:
        def get_embedding_dimension(self):
            return 384

        def get_sentence_embedding_dimension(self):
            raise AssertionError("legacy API called")

    assert _model_dimension(Model()) == 384


def test_embedding_dimension_supports_older_sentence_transformers() -> None:
    class Model:
        def get_sentence_embedding_dimension(self):
            return 128

    assert _model_dimension(Model()) == 128
