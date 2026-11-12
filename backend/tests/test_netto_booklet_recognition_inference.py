
def test_native_image_bbox_clips_visible_intersection_to_page():
    assert _normalized_visible_image_bbox(
        [-22.5, -39.3, 581.1, 866.1],
        566.929,
        793.701,
    ) == [0.0, 0.0, 1.0, 1.0]
    assert _normalized_visible_image_bbox(
        [450.0, 400.0, 600.0, 520.0],
        566.929,
        793.701,
    ) == [0.79375, 0.503968, 0.20625, 0.15119]


def test_native_image_bbox_rejects_nonintersecting_or_degenerate_rectangles():
    with pytest.raises(InferenceRunnerError, match="does not intersect"):
        _normalized_visible_image_bbox([-20, 10, -1, 50], 300, 420)
    with pytest.raises(InferenceRunnerError, match="degenerate"):
        _normalized_visible_image_bbox([10, 10, 10, 50], 300, 420)
    with pytest.raises(InferenceRunnerError, match="invalid"):
        _normalized_visible_image_bbox([0, 0, float("nan"), 50], 300, 420)


def test_native_text_bbox_remains_strict_outside_page():
    with pytest.raises(InferenceRunnerError, match="outside page"):
        _normalized_bbox([-1, 10, 40, 50], 300, 420)