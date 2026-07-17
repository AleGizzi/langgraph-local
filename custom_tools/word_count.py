"""Example custom tool (also serves as documentation)."""
from langchain_core.tools import tool


@tool
def word_count(text: str) -> str:
    """Count the words in a text. Use when asked how long a text is."""
    word_count = len(text.split())
    char_count = len(text)
    return f"{word_count} words, {char_count} chars"
