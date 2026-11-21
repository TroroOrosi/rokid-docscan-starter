package android.media;

import android.graphics.ImageFormat;
import java.nio.ByteBuffer;
import java.util.List;

/** Test-only HAL buffer; Image and Plane constructors are package-private. */
public final class DocScanTestImage extends Image {
    private final List<String> events;
    public ByteBuffer buffer = ByteBuffer.wrap(new byte[]{1, 2, 3});
    public int format = ImageFormat.JPEG;
    public int width = 4032;
    public int height = 3024;
    public int rowStride;
    public int pixelStride;
    /** Semi-planar chroma of a YUV still: with these set the image has three planes. */
    public ByteBuffer chromaU, chromaV;
    public long timestamp = 10L;
    /** On a device each size or plane query is a native call. */
    public int nativeCalls;
    public boolean memoryFailure;
    public boolean timestampMemoryFailure;
    public DocScanTestImage(List<String> events) { this.events = events; }
    @Override public int getFormat() { return format; }
    @Override public int getWidth() { nativeCalls++; return width; }
    @Override public int getHeight() { nativeCalls++; return height; }
    @Override public long getTimestamp() {
        if (timestampMemoryFailure) throw new OutOfMemoryError("synthetic timestamp failure");
        return timestamp;
    }
    @Override public void setTimestamp(long timestamp) { }
    @Override public void close() { events.add("image.close"); }
    @Override public Plane[] getPlanes() {
        if (memoryFailure) throw new OutOfMemoryError("synthetic allocation failure");
        nativeCalls++;
        Plane luma = new Plane() {
            @Override public int getRowStride() { return rowStride; }
            @Override public int getPixelStride() { return pixelStride; }
            @Override public ByteBuffer getBuffer() { return buffer; }
        };
        if (chromaV == null) return new Plane[]{luma};
        return new Plane[]{luma, chroma(chromaU), chroma(chromaV)};
    }

    private Plane chroma(ByteBuffer data) {
        return new Plane() {
            @Override public int getRowStride() { return rowStride; }
            @Override public int getPixelStride() { return 2; }
            @Override public ByteBuffer getBuffer() { return data; }
        };
    }
}
