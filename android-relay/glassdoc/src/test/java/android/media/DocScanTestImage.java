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
    public boolean memoryFailure;
    public DocScanTestImage(List<String> events) { this.events = events; }
    @Override public int getFormat() { return format; }
    @Override public int getWidth() { return width; }
    @Override public int getHeight() { return height; }
    @Override public long getTimestamp() { return 10L; }
    @Override public void setTimestamp(long timestamp) { }
    @Override public void close() { events.add("image.close"); }
    @Override public Plane[] getPlanes() {
        if (memoryFailure) throw new OutOfMemoryError("synthetic allocation failure");
        return new Plane[]{new Plane() {
            @Override public int getRowStride() { return rowStride; }
            @Override public int getPixelStride() { return pixelStride; }
            @Override public ByteBuffer getBuffer() { return buffer; }
        }};
    }
}
