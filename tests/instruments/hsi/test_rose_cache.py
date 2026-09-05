#  SPDX-License-Identifier: GPL-2.0-or-later
"""Rose bake cache (#94): heading changes reuse the baked rose; a scene
rebuild (resize) invalidates it. Companion to the tape strip cache
tests (#93) -- same scene-identity keying."""


def _hsi(qtbot, size=320):
    from pyefis.instruments import hsi
    h = hsi.HSI(font_percent=0.05, cdi_enabled=True, gsi_enabled=True)
    qtbot.addWidget(h)
    h.resize(size, size)
    h.show()
    qtbot.waitExposed(h)
    return h


def test_rose_cache_reused_across_headings(fix, qtbot):
    h = _hsi(qtbot)
    h.setHeading(10.0)
    h.grab()
    rose1 = h._rose_cache[2]
    h.setHeading(200.0)
    h.grab()
    assert h._rose_cache[2] is rose1


def test_rose_cache_invalidated_on_scene_rebuild(fix, qtbot):
    h = _hsi(qtbot)
    h.setHeading(10.0)
    h.grab()
    rose1 = h._rose_cache[2]
    h.resize(280, 280)          # resizeEvent replaces the scene
    h.grab()
    assert h._rose_cache[2] is not rose1


def test_rose_bake_excludes_then_restores_dynamic_items(fix, qtbot):
    h = _hsi(qtbot)
    h.grab()
    # the bake must leave the dynamic card items visible afterwards
    if h.track_item is not None:
        assert h.track_item.isVisible() == h._track_visible()


def test_rotated_rose_reused_within_quantization_step(fix, qtbot):
    # #126: headings inside the same half-degree step share one rotated image
    h = _hsi(qtbot)
    h.setHeading(10.0)
    h.grab()
    img1 = h._rotated_rose_image()
    h.setHeading(10.1)
    h.grab()
    assert h._rotated_rose_image() is img1


def test_rotated_rose_new_image_across_steps(fix, qtbot):
    h = _hsi(qtbot)
    h.setHeading(10.0)
    h.grab()
    img1 = h._rotated_rose_image()
    h.setHeading(11.0)
    h.grab()
    img2 = h._rotated_rose_image()
    assert img2 is not img1
    # jitter back across the boundary hits the retained entry, no re-render
    h.setHeading(10.0)
    assert h._rotated_rose_image() is img1


def test_rotated_rose_cache_bounded(fix, qtbot):
    h = _hsi(qtbot)
    for hdg in range(0, 60, 3):
        h.setHeading(float(hdg))
        h._rotated_rose_image()
    assert len(h._rot_rose_cache) <= h._ROSE_ROT_CACHE_MAX


def test_rotated_rose_invalidated_on_scene_rebuild(fix, qtbot):
    # resize replaces the scene -> new bake cacheKey -> rotated cache misses
    h = _hsi(qtbot)
    h.setHeading(10.0)
    h.grab()
    img1 = h._rotated_rose_image()
    h.resize(280, 280)
    h.grab()
    assert h._rotated_rose_image() is not img1
