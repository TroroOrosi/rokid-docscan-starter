"""Conservative PC-only paper candidates and source-detail diagnostics.

Pillow only. No camera, network, OCR, learned detector, or registration decision.
Automatic geometry assumes ONE bright, flat page on a contrasting background;
unknown layouts and ambiguous outlines never produce an automatic crop.
"""
from __future__ import annotations

import math

from PIL import Image, ImageFilter

from scripts.capture_preflight import MAX_PIXELS, _solve, _validate_corners

DETECTION_EDGE = 512
MAX_FOCUS_SAMPLES = 65536


def focus_metrics(image: Image.Image) -> dict:
    """Sample adjacent native pixels, not a resized/sharpened/tone-corrected image.

    Laplacian variance is noise/texture/scale dependent, NOT a focus probability.
    Compare only the same content at the same source scale and exposure. Flat
    regions (including legitimate blank paper) cannot establish focus failure.
    """
    width, height = image.size
    if min(width, height) < 2 or width * height > MAX_PIXELS:
        raise ValueError('invalid focus image dimensions')
    with image.convert('L') as gray:
        values = gray.tobytes()
        low, high = gray.getextrema()
    stride = 1
    while math.ceil(max(0, width-2)/stride) * math.ceil(max(0, height-2)/stride) > MAX_FOCUS_SAMPLES:
        stride += 1
    total = squares = count = 0
    for y in range(1, height-1, stride):
        for x in range(1, width-1, stride):
            i = y*width+x
            lap = values[i-1]+values[i+1]+values[i-width]+values[i+width]-4*values[i]
            total += lap
            squares += lap*lap
            count += 1
    variance = max(0., squares/count-(total/count)**2) if count else None
    return {'method': 'native_laplacian_v1', 'sample_count': count, 'sample_stride': stride,
            'laplacian_variance': variance, 'calibrated': False,
            'assessment': 'insufficient_texture' if high-low < 16 or not count else 'not_calibrated'}


def _hull(points):
    def cross(a, b, c):
        return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    ordered = sorted(set(points))
    lower, upper = [], []
    for p in ordered:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(ordered):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1]+upper[:-1]


def _area(points):
    return abs(sum(p[0]*points[(i+1) % len(points)][1]-points[(i+1) % len(points)][0]*p[1]
                   for i, p in enumerate(points)))/2


def _otsu(histogram):
    count = sum(histogram)
    full = sum(i*n for i, n in enumerate(histogram))
    left_count = left_sum = 0
    best_score, threshold = -1, 0
    for level, frequency in enumerate(histogram):
        left_count += frequency
        left_sum += level*frequency
        right_count = count-left_count
        if not left_count or not right_count:
            continue
        score = left_count*right_count*(left_sum/left_count-(full-left_sum)/right_count)**2
        if score > best_score:
            best_score, threshold = score, level
    return threshold


def detect_paper(image: Image.Image, *, layout: str) -> dict:
    """Propose a quadrilateral, never certify the physical page or its contents."""
    if layout not in ('single', 'spread', 'unknown'):
        raise ValueError('layout must be single/spread/unknown')
    report = {'method': 'bright_component_quad_v1', 'status': 'unknown',
              'paper_completeness': 'unknown', 'calibrated': False,
              'corners_upright_normalized': None}
    def unknown(reason):
        return dict(report, reason=reason)
    if layout != 'single':
        return unknown('single_page_required')
    if min(image.size) < 32 or image.width*image.height > MAX_PIXELS:
        return unknown('invalid_detection_dimensions')
    with image.convert('L') as gray:
        gray.thumbnail((DETECTION_EDGE, DETECTION_EDGE), Image.Resampling.BILINEAR)
        width, height = gray.size
        histogram = gray.histogram()
        low, high = gray.getextrema()
        if high-low < 40:
            return unknown('insufficient_contrast')
        threshold = _otsu(histogram)
        with gray.point([0 if value <= threshold else 255 for value in range(256)]) as binary:
            # Close tiny text/noise holes on the detection image only, not the source.
            with binary.filter(ImageFilter.MaxFilter(3)) as expanded:
                with expanded.filter(ImageFilter.MinFilter(3)) as mask:
                    foreground = mask.tobytes()
    report['detection_size'] = [width, height]
    seen = bytearray(width*height)
    components = []
    for seed, value in enumerate(foreground):
        if not value or seen[seed]:
            continue
        stack, boundary, count, touches = [seed], [], 0, False
        seen[seed] = 1
        while stack:
            i = stack.pop()
            x, y = i % width, i // width
            count += 1
            edge = x < 3 or y < 3 or x >= width-3 or y >= height-3
            touches |= edge
            for nx, ny in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                if not (0 <= nx < width and 0 <= ny < height):
                    edge = True
                    continue
                j = ny*width+nx
                if not foreground[j]:
                    edge = True
                elif not seen[j]:
                    seen[j] = 1
                    stack.append(j)
            if edge:
                boundary.append((x,y))
        if count >= width*height*.06:
            components.append((count, boundary, touches))
    if not components:
        return unknown('no_large_region')
    components.sort(key=lambda item: item[0], reverse=True)
    count, boundary, touches = components[0]
    if len(components) > 1 and components[1][0] > count*.2:
        return unknown('multiple_regions')
    if touches:
        return unknown('border_contact')
    hull = _hull(boundary)
    hull_area = _area(hull)
    if len(hull) < 4 or not .12 <= hull_area/(width*height) <= .9:
        return unknown('implausible_area')
    quad = list(hull)
    while len(quad) > 4:
        index = min(range(len(quad)), key=lambda i: _area([quad[i-1], quad[i], quad[(i+1) % len(quad)]]))
        del quad[index]
    quad_area = _area(quad)
    if quad_area/hull_area < .94 or count/max(quad_area, 1) < .78:
        return unknown('non_quadrilateral_or_occluded')
    first = min(range(4), key=lambda i: quad[i][0]+quad[i][1])
    quad = quad[first:]+quad[:first]
    points = [[x/(width-1), y/(height-1)] for x, y in quad]
    try:
        _validate_corners(points)
    except ValueError:
        return unknown('ambiguous_corners')
    # Correct angle calculations for a non-square thumbnail.
    sides = [math.dist(quad[i], quad[(i+1) % 4]) for i in range(4)]
    angle = math.degrees(math.atan2(quad[1][1]-quad[0][1], quad[1][0]-quad[0][0]))
    if abs(angle) > 35 or min(sides) < 20 or max(sides[0],sides[2])/min(sides[0],sides[2]) > 2:
        return unknown('extreme_pose')
    if max(sides[1],sides[3])/min(sides[1],sides[3]) > 2:
        return unknown('extreme_pose')
    return dict(report, status='candidate', reason='requires_reference_validation',
                corners_upright_normalized=points, top_edge_degrees=angle,
                quadrilateral_fit=quad_area/hull_area)


def rectify(image: Image.Image, corners: object, *, max_edge: int = 2560) -> tuple[Image.Image, dict]:
    """Perspective derivative plus reversible coordinate map; never overwrite source.

    Four corners describe a FLAT page. A bent spread needs separate-page geometry;
    this transform is not a dewarper. Output aspect is estimated from visible
    edges, not a recovered physical paper aspect ratio.
    """
    if type(max_edge) is not int or not 256 <= max_edge <= 4096:
        raise ValueError('max_edge must be an integer in 256..4096')
    if min(image.size) < 2 or image.width*image.height > MAX_PIXELS:
        raise ValueError('invalid source dimensions')
    if isinstance(corners, (list, tuple)):
        for point in corners:
            if isinstance(point, (list, tuple)) and any(type(v) not in (int, float) for v in point):
                raise ValueError('coordinates must be real numbers, not strings or booleans')
    points, _ = _validate_corners(corners)
    source = [(x*(image.width-1), y*(image.height-1)) for x,y in points]
    w = max(math.dist(source[0],source[1]), math.dist(source[3],source[2]))+1
    h = max(math.dist(source[0],source[3]), math.dist(source[1],source[2]))+1
    reduction = max(1., max(w,h)/max_edge)
    width, height = max(2, round(w/reduction)), max(2, round(h/reduction))
    targets = [(0,0),(width-1,0),(width-1,height-1),(0,height-1)]
    matrix = []
    for (u,v), (x,y) in zip(targets, source):
        matrix.extend([[u,v,1,0,0,0,-x*u,-x*v,x], [0,0,0,u,v,1,-y*u,-y*v,y]])
    coefficients = _solve(matrix)
    if not all(math.isfinite(v) for v in coefficients):
        raise ValueError('nonfinite transform')
    a,b,c,d,e,f,g,hc = coefficients
    # Pillow evaluates pixel centres at x+.5/y+.5; public map uses centres 0..W-1.
    denominator = 1-.5*g-.5*hc
    if abs(denominator) < 1e-10:
        raise ValueError('degenerate sampling transform')
    pil = [a+.5*g, b+.5*hc, c-.5*a-.5*b+.5*denominator,
           d+.5*g, e+.5*hc, f-.5*d-.5*e+.5*denominator, g,hc]
    output = image.transform((width,height), Image.Transform.PERSPECTIVE,
                             [v/denominator for v in pil], Image.Resampling.BICUBIC)
    output.info.clear()
    return output, {'source_size': list(image.size), 'output_size': [width,height],
                    'corners_upright_normalized': points,
                    'output_to_source_homography': coefficients,
                    'coordinate_system': 'upright_pixel_centres',
                    'scale': 'resampled_derivative', 'resampled': True,
                    'recovers_lost_detail': False, 'aspect': 'estimated_from_observed_edges',
                    'top_edge_degrees': math.degrees(math.atan2(source[1][1]-source[0][1],
                                                               source[1][0]-source[0][0]))}
