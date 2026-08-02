from ai_websearch.chunking import chunk_text


def test_plain_text_overlap_starts_at_a_complete_word() -> None:
    text = (
        "Alpha evidence describes the complete first paragraph with enough ordinary words "
        "to cross the configured boundary safely.\n\n"
        "Beta evidence begins the second paragraph and must remain readable."
    )
    chunks = chunk_text(text, chunk_size=120, overlap=35, min_chunk_chars=20)
    assert len(chunks) == 2
    assert chunks[1].startswith("the configured boundary safely.")
    assert not chunks[1].startswith((",", ".", ")"))


def test_structured_schedule_does_not_leak_into_the_next_section() -> None:
    text = """Background prose fills a separate introductory block with supporting history.

## Release schedule
**25 September**: Preview release
**28 September**: Release candidate
**15 November**: Stable release

## Selected for you
Unrelated navigation content follows the article."""
    chunks = chunk_text(text, chunk_size=210, overlap=80, min_chunk_chars=20)
    schedule_chunks = [chunk for chunk in chunks if "15 November" in chunk]
    assert len(schedule_chunks) == 1
    assert "## Release schedule" in schedule_chunks[0]
    assert all(not ("15 November" in chunk and "Selected for you" in chunk) for chunk in chunks)


def test_long_markdown_section_repeats_heading_at_safe_line_boundaries() -> None:
    lines = ["## Test schedule"] + [
        f"**{day} September**: Team Alpha vs Team Beta at the test stadium" for day in range(1, 10)
    ]
    chunks = chunk_text("\n".join(lines), chunk_size=180, overlap=40, min_chunk_chars=20)
    assert len(chunks) > 1
    assert all(chunk.startswith("## Test schedule") for chunk in chunks)
    assert all(len(chunk) <= 180 for chunk in chunks)
    assert all("**" not in chunk.splitlines()[0] for chunk in chunks)


def test_heading_sections_are_preserved_without_blank_lines() -> None:
    text = """# Project status report
Published 2 August 2026
## Completed milestones
**14 July**: Alpha completed
**18 July**: Beta completed
## Release schedule
**25 September**: Preview release
**15 November**: Stable release
## Selected for you
Unrelated navigation links"""
    chunks = chunk_text(text, chunk_size=220, overlap=80, min_chunk_chars=20)
    milestones = next(chunk for chunk in chunks if "18 July" in chunk)
    schedule = next(chunk for chunk in chunks if "25 September" in chunk)
    assert milestones.startswith("## Completed milestones")
    assert "25 September" not in milestones
    assert schedule.startswith("## Release schedule")
    assert "Selected for you" not in schedule


def test_oversized_heading_never_exceeds_chunk_limit() -> None:
    text = f"## {'very long heading ' * 12}\nA short body with useful evidence."
    chunks = chunk_text(text, chunk_size=80, overlap=20, min_chunk_chars=10)
    assert chunks
    assert all(len(chunk) <= 80 for chunk in chunks)
