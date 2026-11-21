package dev.rokid.docscanglass.doc;

import static org.junit.Assert.*;
import android.graphics.ImageFormat;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.params.StreamConfigurationMap;
import android.media.MediaCodecInfo;
import android.media.MediaCodecList;
import android.media.MediaFormat;
import android.media.MediaRecorder;
import android.util.Range;
import android.util.Size;
import java.io.File;
import java.nio.file.Files;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;
import org.robolectric.annotation.Implementation;
import org.robolectric.annotation.Implements;
import org.robolectric.shadow.api.Shadow;
import org.robolectric.shadows.ShadowMediaRecorder;
import org.robolectric.shadows.ShadowMediaExtractor;
import org.robolectric.shadows.util.DataSource;
import org.robolectric.util.ReflectionHelpers;

/** Public capability decisions exercised with advertised-boundary fakes, never hardware evidence. */
@RunWith(RobolectricTestRunner.class)
@Config(sdk=32, manifest=Config.NONE, shadows={CaptureVideoCapabilitiesTest.Characteristics.class,
        CaptureVideoCapabilitiesTest.Map.class, CaptureVideoCapabilitiesTest.Codecs.class,
        CaptureVideoCapabilitiesTest.Codec.class, CaptureVideoCapabilitiesTest.Capabilities.class,
        CaptureVideoCapabilitiesTest.VideoCapabilities.class, CaptureVideoCapabilitiesTest.Recorder.class})
public class CaptureVideoCapabilitiesTest {
    static Size desired = new Size(4032,3024);
    static int alignment, maximumBitrate;
    static boolean fixedFps, surfaceEncoder, sizeAndRate, formatSupported, recorderSize;
    static long minDuration;
    static String codecMime;
    private CaptureVideoRecording.Options options;
    @Before public void setup() {
        alignment=2; maximumBitrate=50_000_000; fixedFps=true; surfaceEncoder=true;
        sizeAndRate=true; formatSupported=true; recorderSize=true; minDuration=33_333_333;
        codecMime="video/avc"; options=CaptureVideoRecording.Options.defaults("test",1,270);
    }
    private String require() throws Exception { return CaptureVideoRecording.requireSupported(Shadow.newInstanceOf(CameraCharacteristics.class), desired, options); }
    private void unsupported(String reason) throws Exception {
        try { require(); fail("explicit profile must be rejected"); }
        catch (CaptureVideoRecording.UnsupportedProfile expected) { assertTrue(expected.getMessage(), expected.getMessage().contains(reason)); }
    }
    @Test public void exactCameraAndSurfaceEncoderProfileIsRequired() throws Exception { assertEquals("boundary-encoder",require()); }
    @Test public void privateCameraSizeAloneDoesNotEstablishRecorderSize() throws Exception { recorderSize=false; unsupported("mediarecorder_size"); }
    @Test public void unknownFrameDurationDoesNotBecomeSupportedRate() throws Exception { minDuration=0; unsupported("frame_rate_unknown"); }
    @Test public void cameraRateBelowRequestedCannotBeSilentlyReduced() throws Exception { minDuration=40_000_000; unsupported("frame_rate_unknown"); }
    @Test public void variableCameraRateIsNotClaimedAsRequestedFixedRate() throws Exception { fixedFps=false; unsupported("fixed_camera_fps"); }
    @Test public void encoderAlignmentMustMatchTheExactRequestedSize() throws Exception { alignment=64; unsupported("encoder_profile"); }
    @Test public void encoderBitrateRangeMustContainTheRequestedBitrate() throws Exception { maximumBitrate=10_000_000; unsupported("encoder_profile"); }
    @Test public void colorFormatMustActuallyAcceptSurfaceInput() throws Exception { surfaceEncoder=false; unsupported("encoder_profile"); }
    @Test public void encoderAdvertisedRateMustMatch() throws Exception { sizeAndRate=false; unsupported("encoder_profile"); }
    @Test public void completeEncoderFormatMustBeSupported() throws Exception { formatSupported=false; unsupported("encoder_profile"); }
    @Test public void avcUnsupportedDoesNotFallbackToHevc() throws Exception { codecMime="video/hevc"; unsupported("avc_surface_encoder"); }
    @Test public void hevcIsAnExplicitIndependentProfile() throws Exception {
        codecMime="video/hevc"; options=new CaptureVideoRecording.Options("test",1,270,"hevc",4032,3024,30,20_000_000);
        assertEquals("boundary-encoder",require());
    }
    @Test public void nonFourByThreeAndUnknownCodecAreRejected() {
        for (String codec : new String[]{"avc","av1"}) {
            try { new CaptureVideoRecording.Options("test",1,270,codec,3840,2160,30,20_000_000); fail("must reject"); }
            catch (IllegalArgumentException expected) { }
        }
    }
    @Test public void actualMediaRecorderAdapterUsesExplicitCodecAndNeverEnablesAudio() throws Exception {
        for (String codec : new String[]{"avc","hevc"}) {
            codecMime="video/"+codec;
            options=new CaptureVideoRecording.Options("test",1,270,codec,4032,3024,30,20_000_000);
            java.lang.reflect.Constructor<?> constructor = Class.forName(CaptureVideoRecording.class.getName()+"$NativePort").getDeclaredConstructor();
            constructor.setAccessible(true);
            CaptureVideoRecording.Port port=(CaptureVideoRecording.Port)constructor.newInstance();
            File file=Files.createTempFile("native-recorder-config", ".mp4").toFile();
            port.prepare(file, Shadow.newInstanceOf(CameraCharacteristics.class), desired, options, reason -> fail(reason));
            MediaRecorder recorder=ReflectionHelpers.getField(port,"recorder"); ShadowMediaRecorder shadow=Shadow.extract(recorder);
            assertEquals(codec.equals("hevc")?MediaRecorder.VideoEncoder.HEVC:MediaRecorder.VideoEncoder.H264,shadow.getVideoEncoder());
            assertEquals(MediaRecorder.VideoSource.SURFACE,shadow.getVideoSource());
            assertEquals(4032,shadow.getVideoWidth()); assertEquals(3024,shadow.getVideoHeight());
            assertEquals(30,shadow.getVideoFrameRate()); assertEquals(20_000_000,shadow.getVideoEncodingBitRate());
            assertEquals(file.getAbsolutePath(),shadow.getOutputPath()); port.close();
            assertEquals(ShadowMediaRecorder.STATE_RELEASED,shadow.getState());
        }
    }
    private CaptureVideoRecording.Port nativePort() throws Exception {
        java.lang.reflect.Constructor<?> constructor=Class.forName(CaptureVideoRecording.class.getName()+"$NativePort").getDeclaredConstructor();
        constructor.setAccessible(true); return (CaptureVideoRecording.Port)constructor.newInstance();
    }
    @Test public void nativeContainerInspectorRecordsActualMetadataWithoutInventingDecodedPts() throws Exception {
        File file=Files.createTempFile("movie-inspection", ".mp4").toFile();
        MediaFormat format=MediaFormat.createVideoFormat("video/hevc",3200,2400);
        format.setLong(MediaFormat.KEY_DURATION,2_000_000); format.setInteger(MediaFormat.KEY_FRAME_RATE,24);
        format.setInteger(MediaFormat.KEY_BIT_RATE,12_000_000);
        ShadowMediaExtractor.addTrack(DataSource.toDataSource(file.getAbsolutePath()),format,new byte[]{1});
        CaptureVideoRecording.FileInfo info=nativePort().inspect(file);
        assertEquals("video/hevc",info.mime); assertEquals(3200,info.width); assertEquals(2400,info.height);
        assertEquals(Long.valueOf(2_000_000),info.durationUs); assertEquals(Integer.valueOf(24),info.frameRate);
        assertEquals(Integer.valueOf(12_000_000),info.bitrate); assertEquals(0,info.audioTracks);
    }
    @Test public void nativeContainerInspectorRejectsAnUnexpectedAudioTrack() throws Exception {
        File file=Files.createTempFile("movie-audio-inspection", ".mp4").toFile();
        MediaFormat format=MediaFormat.createVideoFormat("video/avc",4032,3024); format.setLong(MediaFormat.KEY_DURATION,1_000_000);
        DataSource source=DataSource.toDataSource(file.getAbsolutePath());
        ShadowMediaExtractor.addTrack(source,format,new byte[]{1});
        ShadowMediaExtractor.addTrack(source,MediaFormat.createAudioFormat("audio/mp4a-latm",44100,1),new byte[]{2});
        try{nativePort().inspect(file);fail("reject unexpected audio");}catch(java.io.IOException expected){ }
    }
    @Test public void nativeContainerInspectorCannotTreatMissingDurationAsFinalized() throws Exception {
        File file=Files.createTempFile("movie-duration-inspection", ".mp4").toFile();
        ShadowMediaExtractor.addTrack(DataSource.toDataSource(file.getAbsolutePath()),MediaFormat.createVideoFormat("video/avc",4032,3024),new byte[]{1});
        try{nativePort().inspect(file);fail("reject missing actual duration");}catch(java.io.IOException expected){ }
    }
    @Implements(CameraCharacteristics.class) public static class Characteristics {
        @Implementation protected <T>T get(CameraCharacteristics.Key<T> key) {
            Object value=key.equals(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)?Shadow.newInstanceOf(StreamConfigurationMap.class)
                    :key.equals(CameraCharacteristics.CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES)? new Range[]{new Range<>(fixedFps?30:15,30)}:null;
            @SuppressWarnings("unchecked") T result=(T)value; return result;
        }
    }
    @Implements(StreamConfigurationMap.class) public static class Map {
        @Implementation protected Size[] getOutputSizes(int format) { return new Size[]{desired}; }
        @Implementation protected <T>Size[] getOutputSizes(Class<T> target) { return recorderSize?new Size[]{desired}:new Size[]{new Size(3840,2160)}; }
        @Implementation protected <T>long getOutputMinFrameDuration(Class<T> target,Size size) { return minDuration; }
    }
    @Implements(MediaCodecList.class) public static class Codecs {
        @Implementation protected MediaCodecInfo[] getCodecInfos() { return new MediaCodecInfo[]{Shadow.newInstanceOf(MediaCodecInfo.class)}; }
    }
    @Implements(MediaCodecInfo.class) public static class Codec {
        @Implementation protected boolean isEncoder() { return true; }
        @Implementation protected String[] getSupportedTypes() { return new String[]{codecMime}; }
        @Implementation protected String getName() { return "boundary-encoder"; }
        @Implementation protected MediaCodecInfo.CodecCapabilities getCapabilitiesForType(String mime) {
            MediaCodecInfo.CodecCapabilities caps=Shadow.newInstanceOf(MediaCodecInfo.CodecCapabilities.class);
            caps.colorFormats=new int[]{surfaceEncoder?MediaCodecInfo.CodecCapabilities.COLOR_FormatSurface:19}; return caps;
        }
    }
    @Implements(MediaCodecInfo.CodecCapabilities.class) public static class Capabilities {
        @Implementation protected MediaCodecInfo.VideoCapabilities getVideoCapabilities() { return Shadow.newInstanceOf(MediaCodecInfo.VideoCapabilities.class); }
        @Implementation protected boolean isFormatSupported(MediaFormat format) { return formatSupported; }
    }
    @Implements(MediaCodecInfo.VideoCapabilities.class) public static class VideoCapabilities {
        @Implementation protected int getWidthAlignment() { return alignment; }
        @Implementation protected int getHeightAlignment() { return alignment; }
        @Implementation protected Range<Integer> getBitrateRange() { return new Range<>(1,maximumBitrate); }
        @Implementation protected boolean areSizeAndRateSupported(int w,int h,double rate) { return sizeAndRate; }
    }
    @Implements(MediaRecorder.class) public static class Recorder extends ShadowMediaRecorder {
        @Implementation protected void setAudioSource(int source) { fail("evaluation recorder must not claim microphone"); }
        @Implementation protected void setAudioEncoder(int encoder) { fail("evaluation recorder must not encode audio"); }
    }
}
