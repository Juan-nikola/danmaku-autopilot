import pytest

from danmu_autopilot.release import ImageLock, select_latest_stable


def test_latest_stable_excludes_prereleases():
    releases = [
        {"tag_name": "v2.9.0-rc1", "draft": False, "prerelease": True},
        {"tag_name": "v2.8.3", "draft": False, "prerelease": False},
        {"tag_name": "v2.8.2", "draft": False, "prerelease": False},
    ]
    assert select_latest_stable(releases)["tag_name"] == "v2.8.3"


def test_lock_rejects_mutable_reference():
    with pytest.raises(ValueError, match="sha256"):
        ImageLock(misaka_digest="latest")


def test_backup_engine_requires_digest_even_without_release_tag():
    lock = ImageLock(danmu_api_digest="sha256:" + "b" * 64)
    assert lock.danmu_api_digest.startswith("sha256:")
