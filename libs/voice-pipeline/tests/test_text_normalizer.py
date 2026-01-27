"""Tests for text normalizer."""

import pytest

from voice_pipeline.streaming.normalizer import (
    BasicTextNormalizer,
    TextNormalizer,
    _number_to_words_en,
    _number_to_words_pt,
)


class TestNumberToWordsEN:
    """Tests for English number conversion."""

    def test_zero(self):
        assert _number_to_words_en(0) == "zero"

    def test_single_digit(self):
        assert _number_to_words_en(5) == "five"

    def test_teens(self):
        assert _number_to_words_en(13) == "thirteen"

    def test_tens(self):
        assert _number_to_words_en(40) == "forty"

    def test_tens_with_ones(self):
        assert _number_to_words_en(42) == "forty-two"

    def test_hundred(self):
        assert _number_to_words_en(100) == "one hundred"

    def test_hundred_and_ones(self):
        assert _number_to_words_en(123) == "one hundred twenty-three"

    def test_thousand(self):
        assert _number_to_words_en(1000) == "one thousand"

    def test_complex_number(self):
        assert _number_to_words_en(1234) == "one thousand two hundred thirty-four"

    def test_negative(self):
        assert _number_to_words_en(-5) == "minus five"


class TestNumberToWordsPT:
    """Tests for Portuguese number conversion."""

    def test_zero(self):
        assert _number_to_words_pt(0) == "zero"

    def test_single_digit(self):
        assert _number_to_words_pt(5) == "cinco"

    def test_teens(self):
        assert _number_to_words_pt(13) == "treze"

    def test_tens(self):
        assert _number_to_words_pt(40) == "quarenta"

    def test_tens_with_ones(self):
        assert _number_to_words_pt(42) == "quarenta e dois"

    def test_hundred(self):
        assert _number_to_words_pt(100) == "cem"

    def test_hundred_twenty_three(self):
        assert _number_to_words_pt(123) == "cento e vinte e três"

    def test_thousand(self):
        assert _number_to_words_pt(1000) == "mil"

    def test_two_thousand(self):
        assert _number_to_words_pt(2000) == "dois mil"

    def test_negative(self):
        assert _number_to_words_pt(-5) == "menos cinco"


class TestBasicTextNormalizerEN:
    """Tests for English text normalization."""

    def setup_method(self):
        self.normalizer = BasicTextNormalizer()

    def test_empty_string(self):
        assert self.normalizer.normalize("", "en") == ""

    def test_plain_text_unchanged(self):
        text = "Hello, how are you today?"
        assert self.normalizer.normalize(text, "en") == text

    def test_number_to_words(self):
        result = self.normalizer.normalize("I have 42 apples", "en")
        assert "forty-two" in result

    def test_currency_dollars(self):
        result = self.normalizer.normalize("The price is $10", "en")
        assert "ten dollars" in result

    def test_currency_single_dollar(self):
        result = self.normalizer.normalize("Just $1", "en")
        assert "one dollar" in result

    def test_percentage(self):
        result = self.normalizer.normalize("Growth was 10%", "en")
        assert "ten percent" in result

    def test_acronym_spacing(self):
        result = self.normalizer.normalize("Visit the URL now", "en")
        assert "U R L" in result

    def test_short_caps_not_spaced(self):
        # Only 3+ chars get spaced
        result = self.normalizer.normalize("I am OK", "en")
        assert "O K" not in result  # Only 2 chars, not an acronym


class TestBasicTextNormalizerPT:
    """Tests for Portuguese text normalization."""

    def setup_method(self):
        self.normalizer = BasicTextNormalizer()

    def test_number_pt_br(self):
        result = self.normalizer.normalize("Tenho 42 maçãs", "pt-BR")
        assert "quarenta e dois" in result

    def test_currency_reais(self):
        result = self.normalizer.normalize("O preço é R$10", "pt-BR")
        assert "dez reais" in result

    def test_currency_single_real(self):
        result = self.normalizer.normalize("Apenas R$1", "pt-BR")
        assert "um real" in result

    def test_percentage_pt(self):
        result = self.normalizer.normalize("Crescimento de 10%", "pt-BR")
        assert "dez por cento" in result

    def test_plain_portuguese(self):
        result = self.normalizer.normalize("Olá, como vai?", "pt")
        assert "Olá, como vai?" == result

    def test_acronym_in_portuguese(self):
        result = self.normalizer.normalize("Acesse a URL agora", "pt-BR")
        assert "U R L" in result


class TestTextNormalizerInterface:
    """Tests for the abstract interface."""

    def test_is_abstract(self):
        with pytest.raises(TypeError):
            TextNormalizer()

    def test_basic_implements_interface(self):
        normalizer = BasicTextNormalizer()
        assert isinstance(normalizer, TextNormalizer)
