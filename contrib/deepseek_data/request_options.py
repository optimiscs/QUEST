"""Request options for the opt-in DeepSeek compatibility mode."""
import os


def reasoning_options(default):
    if os.getenv("QUEST_DEEPSEEK_COMPAT") == "1":
        return {"extra_body": {"thinking": {"type": "disabled"}}}
    return default
