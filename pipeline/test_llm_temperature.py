"""llm_temperature clamps Moonshot kimi models to temperature=1."""
from analyze_transcript import llm_temperature


def test_moonshot_clamps_to_one():
    assert llm_temperature("moonshot", 0.3) == 1.0
    assert llm_temperature("moonshot", 0.75) == 1.0
    assert llm_temperature("Moonshot", 0.1) == 1.0


def test_openai_and_gemini_passthrough():
    assert llm_temperature("openai", 0.3) == 0.3
    assert llm_temperature("gemini", 0.75) == 0.75


if __name__ == "__main__":
    test_moonshot_clamps_to_one()
    test_openai_and_gemini_passthrough()
    print("ok")
