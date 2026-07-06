"""Example custom tool (also serves as documentation)."""
from langchain_core.tools import tool


@tool
def word_count(text: str) -> str:
    """Count the words in a text. Use when asked how long a text is."""
    return f"{len(text.split())} words"
