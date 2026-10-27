import re
from typing import List, Optional, Set

# Regex pattern to match alphanumeric sequences, naturally handling punctuation and symbols
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def normalize_and_tokenize(text: Optional[str]) -> List[str]:
    """
    Normalizes text to lowercase and tokenizes by extracting alphanumeric sequences,
    stripping punctuation and whitespace.
    """
    if not text or not isinstance(text, str):
        return []
    return TOKEN_PATTERN.findall(text.lower())


def extract_unique_terms_from_patent(
    title: Optional[str], field_of_invention: Optional[str]
) -> Set[str]:
    """
    Extracts a set of unique normalized terms from a patent's TITLE_OF_INVENTION
    and FIELD_OF_INVENTION fields. Using a set guarantees that each term is indexed
    at most once per patent record.
    """
    combined_text = f"{title or ''} {field_of_invention or ''}".strip()
    return set(normalize_and_tokenize(combined_text))


def tokenize_query(query: str) -> List[str]:
    """
    Tokenizes a search query using the exact same normalization and tokenization
    rules used during index construction. Returns unique terms preserving appearance order.
    """
    raw_tokens = normalize_and_tokenize(query)
    seen = set()
    unique_tokens = []
    for token in raw_tokens:
        if token not in seen:
            seen.add(token)
            unique_tokens.append(token)
    return unique_tokens
