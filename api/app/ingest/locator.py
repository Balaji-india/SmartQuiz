"""Find a model's quote in the source (closed-book rule 2)."""
from rapidfuzz import fuzz

from app.ingest.parser import normalize

FUZZY_THRESHOLD = 90
# Fuzzy matching would find a short quote such as "is a" almost anywhere.
MIN_FUZZY_CHARS = 20


def locate(quote: str, text: str) -> tuple[int, int] | None:
    """(start, end) of the quote in text, or None. text[start:end] is the source span to store."""
    quote = normalize(quote)
    if not quote or len(quote) > len(text):
        return None
    start = text.find(quote)
    if start != -1:
        return start, start + len(quote)
    if len(quote) < MIN_FUZZY_CHARS:
        return None
    match = fuzz.partial_ratio_alignment(quote, text, score_cutoff=FUZZY_THRESHOLD)
    if match is None:
        return None
    start, end = match.dest_start, match.dest_end
    # The alignment can include the spaces around the match.
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return (start, end) if start < end else None
