"""Offline and explicitly opt-in live benchmark support."""

from .corpus import Corpus, load_corpus
from .replay import run_offline_benchmark

__all__ = ["Corpus", "load_corpus", "run_offline_benchmark"]
