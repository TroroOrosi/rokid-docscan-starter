"""Frames of one page, each too dark to read, are placed on each other and added into a page that can be read.

Why it exists (docs/hardware-measurements.md, M-24 and M-25): at the venue's light one frame's level over noise is 2.2
to 4.5 where reading needs about 32, and it grows with the square root of the frames added. Frames of half the sensor's
size read as well as full-size ones only when added on a finer grid at sub-pixel positions (2.3% of characters wrong
against 21.2% without the finer grid, six reads each). Textbook phase correlation cannot place frames this noisy; a
band-passed correlation against the sum so far can.

The scenes here are generated: print-like strokes on paper. No photograph is used.
"""
from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")

from app import gather as g  # noqa: E402

PAPER = 0.6  # the paper's light, of 1


def scene(seed=1, h=384, w=512):
    """Paper with dark strokes 2 to 4 px wide on a 16 px pitch, softened as a lens softens them."""
    rng = np.random.default_rng(seed)
    image = np.full((h, w), PAPER, np.float32)
    for y in range(8, h - 24, 16):
        for x in range(8, w - 24, 16):
            for _ in range(int(rng.integers(1, 4))):
                thin, long = int(rng.integers(2, 5)), int(rng.integers(6, 13))
                top, left = y + int(rng.integers(0, 6)), x + int(rng.integers(0, 6))
                if rng.random() < 0.5:
                    image[top:top + thin, left:left + long] = 0.08
                else:
                    image[top:top + long, left:left + thin] = 0.08
    fy = np.fft.fftfreq(h)[:, None]
    fx = np.fft.rfftfreq(w)[None, :]
    soft = np.exp(-2 * (np.pi * 1.0) ** 2 * (fy ** 2 + fx ** 2))  # a blur of one pixel (sigma)
    return np.fft.irfft2(np.fft.rfft2(image) * soft, s=image.shape).astype(np.float32)


def moved(image, dy, dx):
    """image(y - dy, x - dx) at sub-pixel shifts, by a phase ramp on a mirrored copy."""
    pad = 32
    big = np.pad(image, pad, mode="reflect")
    fy = np.fft.fftfreq(big.shape[0])[:, None]
    fx = np.fft.rfftfreq(big.shape[1])[None, :]
    shifted = np.fft.irfft2(np.fft.rfft2(big) * np.exp(-2j * np.pi * (fy * dy + fx * dx)), s=big.shape)
    return shifted[pad:-pad, pad:-pad].astype(np.float32)


def joined(image):
    return image.reshape(image.shape[0] // 2, 2, image.shape[1] // 2, 2).mean(axis=(1, 3))


def frames(image, shifts, snr1, seed=2):
    """What the camera's half-size stream gives: the scene moved, pixels joined 2x2, one frame's level over noise at a
    sensor pixel `snr1` (2.2 was measured for 10 ms at the venue's light), nothing below black."""
    rng = np.random.default_rng(seed)
    sigma = PAPER / (2 * snr1)
    return [np.maximum(joined(moved(image, dy, dx)) + rng.normal(0, sigma, (image.shape[0] // 2, image.shape[1] // 2)), 0)
            .astype(np.float32) for dy, dx in shifts]


def alike(a, b):
    inner = (slice(24, -24), slice(24, -24))
    return float(np.corrcoef(a[inner].ravel(), b[inner].ravel())[0, 1])


def test_shift_of_finds_a_known_shift_under_the_venue_noise():
    s = scene()
    reference = sum(frames(s, [(0, 0)] * 8, 2.2)) / 8
    dy, dx, strength = g.shift_of(frames(s, [(3.0, -5.0)], 2.2, seed=7)[0], reference, around=(1.0, -2.0), reach=4.0)
    assert abs(2 * dy - 3.0) <= 0.5 and abs(2 * dx + 5.0) <= 0.5
    assert strength > 5


def test_gathered_page_keeps_detail_that_plain_averaging_loses():
    s = scene()
    walk = np.cumsum(np.random.default_rng(3).normal(0, 0.8, (120, 2)), axis=0)
    walk -= walk[0]
    fs = frames(s, walk, 2.2)
    result = g.gather(fs)
    plain = np.repeat(np.repeat(sum(fs) / len(fs), 2, 0), 2, 1)
    assert result.placed and result.used >= 110 and result.total == 120 and result.selection == "none"
    assert result.image.shape == s.shape
    assert alike(result.image, s) > 0.9
    assert alike(result.image, s) > alike(plain, s) + 0.02


def test_level_over_noise_grows_with_the_frames_added():
    s = scene()
    few = g.gather(frames(s, [(0, 0)] * 16, 2.2))
    many = g.gather(frames(s, [(0, 0)] * 64, 2.2))
    assert 1.6 < many.level_over_noise / few.level_over_noise < 2.4  # the square root of four times the frames


def test_smeared_frames_are_left_out():
    result = g.gather(frames(scene(), [(0, 0)] * 40, 2.2), smear=[0.5] * 20 + [6.0] * 20)
    assert (result.used, result.total, result.selection) == (20, 40, "motion")


def test_a_changed_scene_is_not_added():
    a, b = scene(1), scene(9)
    mixed = g.gather(frames(a, [(0, 0)] * 30, 2.2) + frames(b, [(0, 0)] * 10, 2.2, seed=5))
    assert mixed.placed and mixed.used <= 32
    assert alike(mixed.image, a) > 0.9
    lost = g.gather(frames(a, [(0, 0)] * 6, 2.2) + frames(b, [(0, 0)] * 30, 2.2, seed=5))
    assert not lost.placed


def test_no_usable_frame_is_an_answer_not_an_error():
    result = g.gather(frames(scene(), [(0, 0)] * 5, 2.2), smear=[9.0] * 5)
    assert (result.used, result.total, result.placed, result.level_over_noise) == (0, 5, False, 0.0)


def test_bright_frames_stay_in_range():
    result = g.gather([np.full((96, 128), 0.98, np.float32) for _ in range(12)])
    assert np.isfinite(result.image).all()
    assert 0.9 < float(result.image.mean()) < 1.05
