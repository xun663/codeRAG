"""Cleaning pipeline — chains multiple cleaners via the Chain of Responsibility pattern.

Each cleaner runs in sequence; the pipeline collects per-cleaner
statistics so callers can log or display cleaning impact.
"""
from __future__ import annotations

from app.config import settings
from app.core.documents.cleaners.base import BaseCleaner
from app.core.documents.cleaners.rules import (
    DuplicateParagraphDeduplicator,
    HTMLResidueCleaner,
    NoiseLineFilter,
    TrailingWhitespaceRemover,
    UnicodeSanitizer,
    W3SchoolsNavCleaner,
    WhitespaceNormalizer,
)


class CleanerStats:
    """Per-cleaner statistics collected during a cleaning pass."""

    def __init__(self) -> None:
        self.records: list[dict] = []

    def add(self, name: str, before_len: int, after_len: int) -> None:
        self.records.append({
            "cleaner": name,
            "before_chars": before_len,
            "after_chars": after_len,
            "removed_chars": before_len - after_len,
        })

    @property
    def total_removed_chars(self) -> int:
        return sum(r["removed_chars"] for r in self.records)

    @property
    def before_total(self) -> int:
        return self.records[0]["before_chars"] if self.records else 0

    @property
    def after_total(self) -> int:
        return self.records[-1]["after_chars"] if self.records else 0

    def summary(self) -> dict:
        if not self.records:
            return {"enabled": False, "before_chars": 0, "after_chars": 0, "removed_chars": 0}
        return {
            "enabled": True,
            "before_chars": self.before_total,
            "after_chars": self.after_total,
            "removed_chars": self.total_removed_chars,
            "removed_pct": round(self.total_removed_chars / max(self.before_total, 1) * 100, 1),
            "details": self.records,
        }


class CleaningPipeline:
    """Chain-of-responsibility pipeline for text cleaning.

    Usage::

        pipeline = CleaningPipeline()
        text, stats = await pipeline.clean(raw_text, metadata)
    """

    def __init__(self) -> None:
        self.cleaners: list[BaseCleaner] = self._build_cleaners()

    @staticmethod
    def _build_cleaners() -> list[BaseCleaner]:
        """Build the chain based on current configuration."""
        chain: list[BaseCleaner] = []
        enabled = settings.cleaning_enabled

        if enabled:
            # Order matters: coarse → fine
            if settings.cleaning_normalize_unicode:
                chain.append(UnicodeSanitizer())
            if settings.cleaning_remove_html_residue:
                chain.append(HTMLResidueCleaner())
            if settings.cleaning_normalize_whitespace:
                chain.append(TrailingWhitespaceRemover())
                chain.append(WhitespaceNormalizer())
            if settings.cleaning_filter_noise:
                chain.append(NoiseLineFilter())
            if settings.cleaning_deduplicate_paragraphs:
                chain.append(DuplicateParagraphDeduplicator())
            # W3Schools nav stripping — last (coarse structural cut on H1)
            chain.append(W3SchoolsNavCleaner())

        return chain

    async def clean(self, text: str, metadata: dict | None = None) -> tuple[str, CleanerStats]:
        """Run all cleaners in sequence.

        Returns (cleaned_text, stats).
        """
        stats = CleanerStats()
        result = text

        for cleaner in self.cleaners:
            before = len(result)
            result = await cleaner.clean(result, metadata)
            after = len(result)
            stats.add(cleaner.name, before, after)

        return result, stats
