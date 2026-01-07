"""Test script for weighted trail settings calculation."""


def calculate_circular_overlap(win_start: float, win_end: float,
                                cfg_start: float, cfg_end: float,
                                total_count: float) -> float:
    """Calculate overlap between window and config in circular buffer."""
    # Normalize window bounds to [0, total_count) range with wrapping
    win_start = win_start % total_count
    win_end = win_end % total_count

    overlap = 0.0

    # Case 1: Window doesn't wrap (win_start < win_end)
    if win_start <= win_end:
        # Simple overlap calculation
        overlap_start = max(win_start, cfg_start)
        overlap_end = min(win_end, cfg_end)
        overlap = max(0.0, overlap_end - overlap_start)
    else:
        # Case 2: Window wraps around (win_start > win_end in normalized space)
        # Check overlap with first segment [win_start, total_count)
        if cfg_end > win_start:
            overlap_start = max(win_start, cfg_start)
            overlap_end = min(total_count, cfg_end)
            overlap += max(0.0, overlap_end - overlap_start)

        # Check overlap with second segment [0, win_end)
        if cfg_start < win_end:
            overlap_start = max(0.0, cfg_start)
            overlap_end = min(win_end, cfg_end)
            overlap += max(0.0, overlap_end - overlap_start)

    return overlap


def test_case_1():
    """Test: Window centered on single config (no interpolation needed)."""
    print("Test 1: Window centered on single config")
    config_count = 6
    current_progress = 0.5  # Center at index 3
    simultaneous = 1.0      # Window width = 1 config

    center = current_progress * config_count
    half_width = simultaneous / 2.0

    print(f"  Center: {center}, Half-width: {half_width}")
    print(f"  Window: [{center - half_width}, {center + half_width}]")

    for i in range(config_count):
        overlap = calculate_circular_overlap(
            center - half_width, center + half_width,
            float(i), float(i + 1), float(config_count)
        )
        if overlap > 0:
            print(f"  Config {i}: overlap = {overlap:.3f}")

    print()


def test_case_2():
    """Test: Window spanning two configs."""
    print("Test 2: Window spanning two configs")
    config_count = 6
    current_progress = 0.5  # Center at index 3
    simultaneous = 1.5      # Window width = 1.5 configs

    center = current_progress * config_count
    half_width = simultaneous / 2.0

    print(f"  Center: {center}, Half-width: {half_width}")
    print(f"  Window: [{center - half_width}, {center + half_width}]")

    total_weight = 0.0
    for i in range(config_count):
        overlap = calculate_circular_overlap(
            center - half_width, center + half_width,
            float(i), float(i + 1), float(config_count)
        )
        if overlap > 0:
            weight_pct = (overlap / simultaneous) * 100
            print(f"  Config {i}: overlap = {overlap:.3f} ({weight_pct:.1f}%)")
            total_weight += overlap

    print(f"  Total weight: {total_weight:.3f} (should equal {simultaneous})")
    print()


def test_case_3():
    """Test: Window wrapping around (touching index 5, 0, and maybe 1)."""
    print("Test 3: Window wrapping around circular buffer")
    config_count = 6
    current_progress = 0.95  # Near the end
    simultaneous = 1.5       # Window width = 1.5 configs

    center = current_progress * config_count
    half_width = simultaneous / 2.0

    print(f"  Center: {center}, Half-width: {half_width}")
    print(f"  Window: [{center - half_width}, {center + half_width}]")

    total_weight = 0.0
    for i in range(config_count):
        overlap = calculate_circular_overlap(
            center - half_width, center + half_width,
            float(i), float(i + 1), float(config_count)
        )
        if overlap > 0:
            weight_pct = (overlap / simultaneous) * 100
            print(f"  Config {i}: overlap = {overlap:.3f} ({weight_pct:.1f}%)")
            total_weight += overlap

    print(f"  Total weight: {total_weight:.3f} (should equal {simultaneous})")
    print()


def test_case_4():
    """Test: User's example - 20% / 60% / 20% split."""
    print("Test 4: Finding parameters for 20%/60%/20% split")
    config_count = 6
    # We want indices 4, 5, and 0 with weights 20%, 60%, 20%
    # This means simultaneous = 1.0 (total window)
    # And the window should be centered at 5.5 (between 5 and 0)

    current_progress = 5.5 / config_count  # Center at 5.5
    simultaneous = 1.0                      # Window width = 1.0 configs

    center = current_progress * config_count
    half_width = simultaneous / 2.0

    print(f"  Center: {center}, Half-width: {half_width}")
    print(f"  Window: [{center - half_width}, {center + half_width}]")

    total_weight = 0.0
    for i in range(config_count):
        overlap = calculate_circular_overlap(
            center - half_width, center + half_width,
            float(i), float(i + 1), float(config_count)
        )
        if overlap > 0:
            weight_pct = (overlap / simultaneous) * 100
            print(f"  Config {i}: overlap = {overlap:.3f} ({weight_pct:.1f}%)")
            total_weight += overlap

    print(f"  Total weight: {total_weight:.3f} (should equal {simultaneous})")
    print()


if __name__ == "__main__":
    test_case_1()
    test_case_2()
    test_case_3()
    test_case_4()
    print("All tests completed!")
