"""Sentiment defaults to neutral unless explicit directional language is present."""
import re
import unittest


def infer_sentiment(text: str) -> str:
    """
    Infer sentiment from text using the neutral-default rule.

    Default to neutral. Use bullish or bearish ONLY when the text says a market,
    company, or asset should move in a specific direction. A negative-sounding
    topic (conquest, censorship, acquisition) is NOT a direction.
    """
    text = (text or '').lower()

    bullish_phrases = [
        'bullish on', 'shares should rise', 'price target above', 'buy rating',
        'upgrade to buy', 'expect gains', 'upside to', 'long position',
    ]
    bearish_phrases = [
        'bearish on', 'shares should fall', 'price target below', 'sell rating',
        'downgrade to sell', 'expect losses', 'downside to', 'short position',
    ]

    if any(p in text for p in bullish_phrases):
        return 'bullish'
    elif any(p in text for p in bearish_phrases):
        return 'bearish'
    return 'neutral'


class SentimentRuleTest(unittest.TestCase):

    def test_default_neutral(self):
        self.assertEqual(infer_sentiment(""), "neutral")
        self.assertEqual(infer_sentiment("The Fed raised rates by 25 bp."), "neutral")
        self.assertEqual(infer_sentiment("AI capex reached $400B in Q2."), "neutral")

    def test_explicit_bullish(self):
        self.assertEqual(infer_sentiment("The analyst is bullish on NVDA."), "bullish")
        self.assertEqual(infer_sentiment("We expect shares should rise after earnings."), "bullish")
        self.assertEqual(infer_sentiment("Price target above $200 for AAPL."), "bullish")

    def test_explicit_bearish(self):
        self.assertEqual(infer_sentiment("Baker is bearish on real estate."), "bearish")
        self.assertEqual(infer_sentiment("Shares should fall if tariffs pass."), "bearish")
        self.assertEqual(infer_sentiment("The bank issued a sell rating."), "bearish")

    def test_negative_topic_not_bearish(self):
        # Conquest, censorship, acquisition - sounds negative but no direction
        self.assertEqual(
            infer_sentiment("How a few hundred soldiers toppled empires."),
            "neutral"
        )
        self.assertEqual(
            infer_sentiment("DoxxNet censorship and privacy concerns."),
            "neutral"
        )
        self.assertEqual(
            infer_sentiment("Stripe acquiring OpenRouter for $3B."),
            "neutral"
        )
        # Risk, collapse, avoid - topic keywords, not explicit direction
        self.assertEqual(
            infer_sentiment("Regulatory risk in the healthcare sector."),
            "neutral"
        )
        self.assertEqual(
            infer_sentiment("The housing market may collapse."),
            "neutral"
        )
        self.assertEqual(
            infer_sentiment("Investors should avoid cyclicals."),
            "neutral"
        )

    def test_positive_topic_not_bullish(self):
        # Growth, opportunity - topic keywords, not explicit direction
        self.assertEqual(
            infer_sentiment("AI growth continues unabated."),
            "neutral"
        )
        self.assertEqual(
            infer_sentiment("This creates an opportunity for founders."),
            "neutral"
        )


if __name__ == "__main__":
    unittest.main()
