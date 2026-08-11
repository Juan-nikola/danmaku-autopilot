from danmu_autopilot.domain import Comment, Segment
from danmu_autopilot.xml import deduplicate, map_timeline, parse_xml, serialize_xml


COMMENTS = (
    Comment(5_000, 1, 0xFFFFFF, 25, "正片", "fixture"),
    Comment(10_000, 5, 0xFF0000, 36, "正片", "fixture"),
)


def test_negative_shift_drops_only_pre_roll():
    comments = (
        Comment(7_100_000, 1, 0xFFFFFF, 25, "垫片", "bili:1"),
        Comment(7_205_000, 5, 0xFF0000, 36, "正片", "bili:1"),
    )
    result = map_timeline(
        comments,
        (Segment(1, 7_200_000, 8_460_000, 0),),
    )
    assert result == (Comment(5_000, 5, 0xFF0000, 36, "正片", "bili:1"),)


def test_round_trip_preserves_mode_color_and_size():
    parsed = parse_xml(serialize_xml(COMMENTS, {"source": "fixture"}), "fixture")
    assert [(c.mode, c.color, c.size) for c in parsed] == [
        (c.mode, c.color, c.size) for c in COMMENTS
    ]


def test_deduplicate_keeps_earliest_source_priority_winner():
    comments = (
        Comment(1_000, 1, 0xFFFFFF, 25, " hello ", "low"),
        Comment(1_050, 1, 0xFFFFFF, 25, "hello", "high"),
        Comment(3_000, 1, 0xFFFFFF, 25, "hello", "high"),
    )
    assert deduplicate(comments, window_ms=100, source_priority={"high": 0, "low": 1}) == (
        comments[1],
        comments[2],
    )
