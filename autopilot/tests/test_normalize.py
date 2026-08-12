import pytest

from danmu_autopilot.normalize import AliasCatalog, expand_aliases, parse_match_context


@pytest.mark.parametrize(
    ("name", "title", "season", "episode"),
    [
        ("Show.Name.S03E08.2160p.WEB-DL.mkv", "Show Name", 3, 8),
        ("躲在超市门口抽烟的两人 - 02.mp4", "躲在超市门口抽烟的两人", 1, 2),
        ("东京吃人 第2季 03", "东京吃人", 2, 3),
    ],
)
def test_parse_multilingual_match_context(name, title, season, episode):
    result = parse_match_context(name)
    assert (result.title, result.season, result.episode) == (title, season, episode)
    assert result.original_filename == name


def test_noise_and_year_are_not_episode_numbers():
    movie = parse_match_context("The.Movie.2024.1080p.BluRay.mkv")
    assert movie.episode is None
    assert movie.season == 1
    assert movie.title == "The Movie 2024"


def test_alias_priority_is_learned_metadata_local_original_and_deduplicated():
    catalog = AliasCatalog(
        local={"东京吃人": ("Tokyo Ghoul",)},
        metadata={"东京吃人": ("Tokyo Ghoul (2014)",)},
        learned={"东京吃人": ("Tokyo Ghoul", "Tokyo Ghoul: Root A")},
    )
    assert expand_aliases("东京吃人", catalog) == (
        "Tokyo Ghoul",
        "Tokyo Ghoul: Root A",
        "Tokyo Ghoul (2014)",
        "东京吃人",
    )
