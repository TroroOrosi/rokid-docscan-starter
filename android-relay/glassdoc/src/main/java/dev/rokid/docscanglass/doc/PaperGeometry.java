// AGENT_APPROVED=1: authorized explicit Android comparison; device dispatch zero.
package dev.rokid.docscanglass.doc;

import java.nio.ByteBuffer;

/** Bounded, provisional bright-region geometry. Never a crop or page-completeness verdict. */
final class PaperGeometry {
    private PaperGeometry() { }

    static Box candidate(ByteBuffer plane, int width, int height, int rowStride, int pixelStride) {
        if (plane == null || width <= 0 || height <= 0 || rowStride <= 0 || pixelStride <= 0
                || rowStride < (long)(width - 1) * pixelStride + 1) return null;
        long end = plane.position() + (long)(height - 1) * rowStride + (long)(width - 1) * pixelStride;
        if (end >= plane.limit()) return null;
        double scale = Math.min(1d, 64d / Math.max(width, height));
        int w = Math.max(1, (int)(width * scale)), h = Math.max(1, (int)(height * scale));
        if (w < 8 || h < 8) return null;
        int[] luma = new int[w * h];
        for (int y = 0; y < h; y++) for (int x = 0; x < w; x++) {
            int at = plane.position() + y * height / h * rowStride + x * width / w * pixelStride;
            luma[y * w + x] = plane.get(at) & 255;
        }
        int[] box = PaperCrop.box(luma, w, h);
        // Touching the image boundary is ambiguous, not evidence that the paper is complete.
        return box == null || box[0] == 0 || box[1] == 0 || box[2] == w || box[3] == h
                ? null : new Box(box[0], box[1], box[2], box[3], w, h);
    }

    static final class Box {
        final int left, top, right, bottom, width, height;
        Box(int left, int top, int right, int bottom, int width, int height) {
            if (left < 0 || top < 0 || right <= left || bottom <= top || right > width || bottom > height)
                throw new IllegalArgumentException("invalid proposal bounds");
            this.left = left; this.top = top; this.right = right; this.bottom = bottom;
            this.width = width; this.height = height;
        }
        int[] edges() { return new int[]{left, top, right, bottom}; }
        Box rotate(int clockwise) {
            return switch (clockwise) {
                case 0 -> this;
                case 90 -> new Box(height - bottom, left, height - top, right, height, width);
                case 180 -> new Box(width - right, height - bottom, width - left, height - top, width, height);
                case 270 -> new Box(top, width - right, bottom, width - left, height, width);
                default -> throw new IllegalArgumentException("unsupported proposal rotation");
            };
        }
        /** Camera2 AE regions include the extra centre crop needed by the output aspect. */
        int[] sensorRegion(int left, int top, int right, int bottom, int streamWidth, int streamHeight) {
            if (left < 0 || top < 0 || right <= left || bottom <= top || streamWidth <= 0 || streamHeight <= 0)
                return null;
            double w = (double)right - left, h = (double)bottom - top;
            double usedW = Math.min(w, h * streamWidth / streamHeight);
            double usedH = Math.min(h, w * streamHeight / streamWidth);
            double x = left + (w - usedW) / 2, y = top + (h - usedH) / 2;
            return new int[]{(int)Math.floor(x + usedW * this.left / width),
                    (int)Math.floor(y + usedH * this.top / height),
                    (int)Math.ceil(x + usedW * this.right / width),
                    (int)Math.ceil(y + usedH * this.bottom / height)};
        }
        boolean near(Box other) {
            return other != null && width == other.width && height == other.height
                    && Math.abs(left - other.left) <= 1 && Math.abs(top - other.top) <= 1
                    && Math.abs(right - other.right) <= 1 && Math.abs(bottom - other.bottom) <= 1;
        }
    }

    /** Two consistent observations, reset by uncertainty or any distinct page scene. */
    static final class Tracker {
        private long scene = -1;
        private Box previous;
        Box observe(Box candidate, long nextScene) {
            if (nextScene < scene) return null;
            if (nextScene != scene) { scene = nextScene; previous = null; }
            if (candidate == null) { previous = null; return null; }
            if (candidate.near(previous)) return previous;
            previous = candidate;
            return null;
        }
    }
}
