"""Synthetic geometry tests; never evidence of physical page completeness."""
import importlib
import importlib.util
import math

import pytest
from PIL import Image, ImageChops, ImageDraw, ImageFilter


def geometry():
    assert importlib.util.find_spec('scripts.capture_geometry'), 'geometry component missing'
    return importlib.import_module('scripts.capture_geometry')


def sheet(size=(600, 500), points=((130, 60), (510, 100), (460, 440), (90, 390))):
    image = Image.new('RGB', size, (30, 30, 30))
    draw = ImageDraw.Draw(image)
    draw.polygon(points, fill=(225, 225, 225))
    for y in range(140, 320, 25):
        draw.line((180, y, 390, y), fill=(30, 30, 30), width=3)
    return image


def test_auto_quadrilateral_is_only_an_unvalidated_candidate():
    report = geometry().detect_paper(sheet(), layout='single')
    assert report['status'] == 'candidate'
    assert report['paper_completeness'] == 'unknown'
    assert report['calibrated'] is False
    assert len(report['corners_upright_normalized']) == 4
    expected = [(130/599, 60/499), (510/599, 100/499), (460/599, 440/499), (90/599, 390/499)]
    for observed, actual in zip(report['corners_upright_normalized'], expected):
        assert math.dist(observed, actual) < .025


@pytest.mark.parametrize('layout', ['spread', 'unknown'])
def test_auto_never_rectifies_a_spread_as_one_flat_page(layout):
    report = geometry().detect_paper(sheet(), layout=layout)
    assert report['status'] == 'unknown'
    assert report['reason'] == 'single_page_required'


@pytest.mark.parametrize('color', ['white', 'black', (90, 90, 90)])
def test_flat_photographs_are_not_paper_evidence(color):
    report = geometry().detect_paper(Image.new('RGB', (500, 400), color), layout='single')
    assert report['status'] == 'unknown'
    assert report['corners_upright_normalized'] is None


def test_page_touching_image_edge_is_not_corrected_as_complete():
    image = sheet(points=((0, 30), (500, 40), (450, 460), (0, 450)))
    report = geometry().detect_paper(image, layout='single')
    assert report['status'] == 'unknown'
    assert report['reason'] == 'border_contact'


def test_two_distinct_pages_are_ambiguous_even_when_declared_single():
    image = Image.new('RGB', (600, 400), (20, 20, 20))
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 50, 260, 350), fill='white')
    draw.rectangle((340, 50, 560, 350), fill='white')
    report = geometry().detect_paper(image, layout='single')
    assert report['status'] == 'unknown'
    assert report['reason'] == 'multiple_regions'


def test_circle_is_not_approximated_as_a_paper_rectangle():
    image = Image.new('RGB', (500, 500), (20, 20, 20))
    ImageDraw.Draw(image).ellipse((40, 40, 460, 460), fill='white')
    assert geometry().detect_paper(image, layout='single')['status'] == 'unknown'


def test_identity_transform_preserves_size_and_pixels():
    image = Image.new('RGB', (220, 160))
    image.putdata([(x % 256, y % 256, (x+y) % 256) for y in range(160) for x in range(220)])
    corrected, plan = geometry().rectify(image, [[0, 0], [1, 0], [1, 1], [0, 1]])
    assert corrected.size == image.size
    assert ImageChops.difference(image, corrected).getbbox() is None
    assert plan['resampled'] is True
    assert plan['recovers_lost_detail'] is False
    assert plan['coordinate_system'] == 'upright_pixel_centres'


def test_perspective_mapping_contains_each_supplied_corner():
    points = [[.15, .08], [.85, .15], [.78, .92], [.1, .8]]
    corrected, plan = geometry().rectify(sheet(), points)
    w, h = corrected.size
    a,b,c,d,e,f,g,hc = plan['output_to_source_homography']
    for (x, y), (u, v) in zip([(0,0), (w-1,0), (w-1,h-1), (0,h-1)], points):
        denominator = g*x+hc*y+1
        assert (a*x+b*y+c)/denominator == pytest.approx(u*599, abs=1e-6)
        assert (d*x+e*y+f)/denominator == pytest.approx(v*499, abs=1e-6)
    assert abs(plan['top_edge_degrees']) > 1


@pytest.mark.parametrize('corners', [
    [[False,0],[1,0],[1,1],[0,1]], [[0,0],[1,1],[1,0],[0,1]],
    [[0,0],[float('nan'),0],[1,1],[0,1]], [[0,0],[1,0],[1,1]],
])
def test_invalid_geometry_never_generates_a_candidate(corners):
    with pytest.raises(ValueError):
        geometry().rectify(sheet(), corners)


def test_output_is_bounded_and_not_claimed_source_scale():
    corrected, plan = geometry().rectify(Image.new('RGB', (3600, 2400), 'white'),
        [[0,0],[1,0],[1,1],[0,1]])
    assert max(corrected.size) <= 2560
    assert plan['scale'] == 'resampled_derivative'


def test_focus_metric_distinguishes_same_content_synthetic_blur():
    module = geometry()
    image = Image.new('RGB', (400, 300), 'white')
    draw = ImageDraw.Draw(image)
    for y in range(15, 280, 12):
        draw.line((20,y,380,y), fill='black', width=2)
    blurred = image.filter(ImageFilter.GaussianBlur(2))
    sharp_result = module.focus_metrics(image)
    blur_result = module.focus_metrics(blurred)
    assert sharp_result['laplacian_variance'] > blur_result['laplacian_variance'] * 5
    assert sharp_result['assessment'] == blur_result['assessment'] == 'not_calibrated'
    assert sharp_result['sample_count'] <= 65536


def test_blank_detail_is_not_reported_as_failed_focus():
    result = geometry().focus_metrics(Image.new('RGB', (512,512), 'white'))
    assert result['laplacian_variance'] == 0
    assert result['assessment'] == 'insufficient_texture'
