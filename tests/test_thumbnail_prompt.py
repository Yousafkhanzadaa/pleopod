from app.agents.prompts import thumbnail_prompt

SCRIPT = {
    "title": "AI's Catastrophic Risks: A Stark Warning from Experts",
    "summary": (
        "A recent study surveyed 272 AI experts, revealing a significant "
        "probability of catastrophic AI outcomes within five years."
    ),
    "description": "A factual short video about the findings and their limitations.",
    "transcript": "Arman explains the survey, its findings, and how to read them.",
}

JOB = {
    "topic": "Expert views on long-term AI risk",
    "category": "Technology news",
    "audience": "curious technology professionals",
}


def test_thumbnail_prompt_is_one_short_title_and_summary_paragraph() -> None:
    prompt = thumbnail_prompt(SCRIPT, JOB)

    assert prompt == (
        'Generate a YouTube thumbnail for the video titled "AI\'s Catastrophic Risks: A Stark '
        'Warning from Experts". Video information: A recent study surveyed 272 AI '
        "experts, revealing a significant probability of catastrophic AI outcomes "
        "within five years."
    )
    assert "\n" not in prompt
    assert SCRIPT["transcript"] not in prompt
    assert JOB["audience"] not in prompt
    assert "style" not in prompt.lower()
    assert "layout" not in prompt.lower()


def test_thumbnail_prompt_falls_back_to_description() -> None:
    prompt = thumbnail_prompt(
        {
            "title": "A New AI Chip",
            "summary": "",
            "description": "The video explains what the chip changes for developers.",
        }
    )

    assert prompt == (
        'Generate a YouTube thumbnail for the video titled "A New AI Chip". Video information: '
        "The video explains what the chip changes for developers."
    )


def test_thumbnail_prompt_falls_back_to_job_topic() -> None:
    prompt = thumbnail_prompt({}, {"topic": "A new database release"})

    assert prompt == 'Generate a YouTube thumbnail for the video titled "A new database release".'
