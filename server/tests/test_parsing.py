from bili_client import BiliClient, SubtitleSegment


def test_direct_bvid():
    c = BiliClient()
    assert c.resolve_bvid("BV1UD421W7Gc") == "BV1UD421W7Gc"
    assert c.resolve_bvid("https://www.bilibili.com/video/BV1UD421W7Gc?p=3") == "BV1UD421W7Gc"


def test_subtitle_dataclass():
    seg = SubtitleSegment(1.2, 3.4, "hello")
    assert seg.text == "hello"
