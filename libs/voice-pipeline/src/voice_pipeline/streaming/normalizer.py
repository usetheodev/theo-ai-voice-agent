"""Text normalization for TTS input.

Transforms text containing numbers, currencies, percentages,
and abbreviations into speakable forms for TTS engines.
"""

import re
from abc import ABC, abstractmethod


class TextNormalizer(ABC):
    """Abstract interface for text normalization before TTS."""

    @abstractmethod
    def normalize(self, text: str, language: str = "en") -> str:
        """Normalize text for TTS consumption.

        Args:
            text: Raw text to normalize.
            language: Language code (e.g., "en", "pt-BR", "pt").

        Returns:
            Normalized text suitable for TTS.
        """
        ...


# Number-to-words mappings

_ONES_EN = [
    "", "one", "two", "three", "four", "five", "six", "seven",
    "eight", "nine", "ten", "eleven", "twelve", "thirteen",
    "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen",
]
_TENS_EN = [
    "", "", "twenty", "thirty", "forty", "fifty",
    "sixty", "seventy", "eighty", "ninety",
]

_ONES_PT = [
    "", "um", "dois", "três", "quatro", "cinco", "seis", "sete",
    "oito", "nove", "dez", "onze", "doze", "treze",
    "quatorze", "quinze", "dezesseis", "dezessete", "dezoito", "dezenove",
]
_TENS_PT = [
    "", "", "vinte", "trinta", "quarenta", "cinquenta",
    "sessenta", "setenta", "oitenta", "noventa",
]
_HUNDREDS_PT = [
    "", "cento", "duzentos", "trezentos", "quatrocentos", "quinhentos",
    "seiscentos", "setecentos", "oitocentos", "novecentos",
]


def _number_to_words_en(n: int) -> str:
    """Convert integer to English words (0-999999)."""
    if n == 0:
        return "zero"
    if n < 0:
        return "minus " + _number_to_words_en(-n)

    parts = []

    if n >= 1000:
        thousands = n // 1000
        n %= 1000
        parts.append(_number_to_words_en(thousands) + " thousand")

    if n >= 100:
        parts.append(_ONES_EN[n // 100] + " hundred")
        n %= 100

    if n >= 20:
        tens_word = _TENS_EN[n // 10]
        ones_word = _ONES_EN[n % 10]
        if ones_word:
            parts.append(f"{tens_word}-{ones_word}")
        else:
            parts.append(tens_word)
    elif n > 0:
        parts.append(_ONES_EN[n])

    return " ".join(parts)


def _number_to_words_pt(n: int) -> str:
    """Convert integer to Portuguese words (0-999999)."""
    if n == 0:
        return "zero"
    if n < 0:
        return "menos " + _number_to_words_pt(-n)
    if n == 100:
        return "cem"

    parts = []

    if n >= 1000:
        thousands = n // 1000
        n %= 1000
        if thousands == 1:
            parts.append("mil")
        else:
            parts.append(_number_to_words_pt(thousands) + " mil")

    if n >= 100:
        parts.append(_HUNDREDS_PT[n // 100])
        n %= 100

    if n >= 20:
        tens_word = _TENS_PT[n // 10]
        ones_word = _ONES_PT[n % 10]
        if ones_word:
            parts.append(tens_word)
            parts.append(ones_word)
        else:
            parts.append(tens_word)
    elif n > 0:
        parts.append(_ONES_PT[n])

    return " e ".join(parts)


def _is_pt(language: str) -> bool:
    """Check if language is Portuguese."""
    lang = language.lower()
    return lang.startswith("pt")


class BasicTextNormalizer(TextNormalizer):
    """Basic text normalizer for TTS.

    Handles:
    - Numbers → words (PT-BR and EN)
    - Currency: R$, $ → words
    - Percentages: 10% → words
    - All-caps acronyms (3+ chars): "URL" → "U R L"
    """

    # Pattern for currency: R$123, $45, etc.
    _CURRENCY_RE = re.compile(r"(R\$|€|\$|£)\s*(\d+(?:[.,]\d+)?)")

    # Pattern for percentages: 10%, 5.5%
    _PERCENT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")

    # Pattern for standalone numbers
    _NUMBER_RE = re.compile(r"\b(\d+)\b")

    # Pattern for all-caps acronyms (3+ letters, no lowercase around)
    _ACRONYM_RE = re.compile(r"\b([A-Z]{3,})\b")

    def normalize(self, text: str, language: str = "en") -> str:
        """Normalize text for TTS."""
        if not text:
            return text

        pt = _is_pt(language)

        # Order matters: currencies before numbers
        text = self._normalize_currencies(text, pt)
        text = self._normalize_percentages(text, pt)
        text = self._normalize_numbers(text, pt)
        text = self._normalize_acronyms(text)

        return text

    def _normalize_currencies(self, text: str, pt: bool) -> str:
        """Convert currency amounts to words."""
        def replace_currency(match):
            symbol = match.group(1)
            amount_str = match.group(2).replace(",", ".")
            amount = float(amount_str)
            integer_part = int(amount)

            if pt:
                num_words = _number_to_words_pt(integer_part)
                if symbol == "R$":
                    unit = "real" if integer_part == 1 else "reais"
                elif symbol == "$":
                    unit = "dólar" if integer_part == 1 else "dólares"
                elif symbol == "€":
                    unit = "euro" if integer_part == 1 else "euros"
                elif symbol == "£":
                    unit = "libra" if integer_part == 1 else "libras"
                else:
                    unit = symbol
            else:
                num_words = _number_to_words_en(integer_part)
                if symbol == "R$":
                    unit = "real" if integer_part == 1 else "reais"
                elif symbol == "$":
                    unit = "dollar" if integer_part == 1 else "dollars"
                elif symbol == "€":
                    unit = "euro" if integer_part == 1 else "euros"
                elif symbol == "£":
                    unit = "pound" if integer_part == 1 else "pounds"
                else:
                    unit = symbol

            return f"{num_words} {unit}"

        return self._CURRENCY_RE.sub(replace_currency, text)

    def _normalize_percentages(self, text: str, pt: bool) -> str:
        """Convert percentages to words."""
        def replace_percent(match):
            amount_str = match.group(1).replace(",", ".")
            amount = float(amount_str)
            integer_part = int(amount)

            if pt:
                return _number_to_words_pt(integer_part) + " por cento"
            else:
                return _number_to_words_en(integer_part) + " percent"

        return self._PERCENT_RE.sub(replace_percent, text)

    def _normalize_numbers(self, text: str, pt: bool) -> str:
        """Convert standalone numbers to words."""
        def replace_number(match):
            n = int(match.group(1))
            if n > 999999:
                return match.group(0)  # Too large, leave as-is
            if pt:
                return _number_to_words_pt(n)
            else:
                return _number_to_words_en(n)

        return self._NUMBER_RE.sub(replace_number, text)

    def _normalize_acronyms(self, text: str) -> str:
        """Space out all-caps acronyms for letter-by-letter pronunciation."""
        def replace_acronym(match):
            return " ".join(match.group(0))

        return self._ACRONYM_RE.sub(replace_acronym, text)
