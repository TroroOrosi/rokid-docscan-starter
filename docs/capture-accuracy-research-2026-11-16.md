# Capture accuracy: what the literature and the platform documentation say (2026-11-16)

Status: Research. Literature and platform documentation read on 2026-11-16. Nothing in this file was run on the
glasses or the phone, and no repository code was changed. Every in-house number quoted here comes from the project
record as it stood that day and is labelled "in-house"; it was not re-measured.

## How to read this file

Each statement carries one of three marks.

- **[S]** from the source named beside it.
- **[I]** inference (mine): arithmetic or reasoning that joins a source to this system. Not in any source.
- **[NF]** not found: looked for and not found, or the source could not be fetched.

The fetch tool used for this work returns either the page itself or an extraction of it made by a small model. The
second kind is less reliable for numbers. The "Read" column in the source table says which one each source was:

- **D** read directly (page text or PDF pages seen as they are).
- **X** read through the tool's extraction. Check a number against the source before a design depends on it.
- **N** not fetched. Nothing about its contents is asserted here beyond what another fetched source says of it.

All URLs were read on 2026-11-16.

## Sources

| Id | Source | URL | Read |
|---|---|---|---|
| LIBA | Liba et al., "Handheld Mobile Photography in Very Low Light", SIGGRAPH Asia 2019 | https://ar5iv.labs.arxiv.org/html/1910.11336 | X (three passes) |
| WRON | Wronski et al., "Handheld Multi-Frame Super-Resolution", SIGGRAPH 2019 | https://ar5iv.labs.arxiv.org/html/1905.03277 | X (two passes) |
| HDRP | Hasinoff et al., "Burst photography for high dynamic range and low-light imaging on mobile cameras", SIGGRAPH Asia 2016 | abstract: https://research.google/pubs/burst-photography-for-high-dynamic-range-and-low-light-imaging-on-mobile-cameras/ | abstract X; full text N (the PDF at hdrplusdata.org is over the tool's 10 MB limit; three mirrors refused) |
| IPOL | Monod, Delon, Veit, "An Analysis and Implementation of the HDR+ Burst Denoising Method", IPOL 2021 (a re-implementation; secondary for HDR+) | https://ar5iv.labs.arxiv.org/html/2110.09354 | X |
| NSBL | Google Research blog, "Night Sight: Seeing in the Dark on Pixel Phones", 2018 (vendor) | https://research.google/blog/night-sight-seeing-in-the-dark-on-pixel-phones/ | X |
| FBA | Delbracio and Sapiro, "Burst Deblurring: Removing Camera Shake Through Fourier Burst Accumulation", CVPR 2015 (arXiv 1505.02731) | https://ar5iv.labs.arxiv.org/html/1505.02731 | X (two passes) |
| FBAV | Delbracio and Sapiro, "Hand-held Video Deblurring via Efficient Fourier Aggregation", 2015 (arXiv 1509.05251) | https://ar5iv.labs.arxiv.org/html/1509.05251 | X |
| PARK | Park and Levoy, "Gyro-Based Multi-Image Deconvolution for Removing Handshake Blur", CVPR 2014 | https://www.cv-foundation.org/openaccess/content_cvpr_2014/papers/Park_Gyro-Based_Multi-Image_Deconvolution_2014_CVPR_paper.pdf | D (all 8 pages) |
| HAS10 | Hasinoff, Durand, Freeman, "Noise-Optimal Capture for High Dynamic Range Photography", CVPR 2010 | https://people.csail.mit.edu/hasinoff/pubs/hasinoff-hdrnoise-2010.pdf | D (pages 1-4 of 8) |
| MUST | "Gyroscope-Aided Motion Deblurring with Deep Networks" (arXiv 1810.00986; the page read did not show the authors) | https://ar5iv.labs.arxiv.org/html/1810.00986 | X |
| KARP | Karpenko et al., "Digital Video Stabilization and Rolling Shutter Correction using Gyroscopes", Stanford CSTR 2011-03 | https://graphics.stanford.edu/papers/stabilization/ | N (certificate errors on both Stanford hosts) |
| DRIZ | Fruchter and Hook, "Drizzle: A Method for the Linear Reconstruction of Undersampled Images", PASP 2002 | https://arxiv.org/html/astro-ph/9808087v2 | X |
| A-META | Android reference, `CameraMetadata` | https://developer.android.com/reference/android/hardware/camera2/CameraMetadata | D for MOTION_TRACKING and the timestamp sources; X for BURST_CAPTURE, RAW, MANUAL_SENSOR, hardware levels |
| A-RES | Android reference, `CaptureResult` | https://developer.android.com/reference/android/hardware/camera2/CaptureResult | D for SENSOR_TIMESTAMP, SENSOR_ROLLING_SHUTTER_SKEW, SENSOR_SENSITIVITY, SENSOR_NOISE_PROFILE, SENSOR_FRAME_DURATION; X for CONTROL_POST_RAW_SENSITIVITY_BOOST |
| A-CHAR | Android reference, `CameraCharacteristics` | https://developer.android.com/reference/android/hardware/camera2/CameraCharacteristics | X |
| A-MAP | Android reference, `StreamConfigurationMap` | https://developer.android.com/reference/android/hardware/camera2/params/StreamConfigurationMap | D (stall durations) |
| A-SENS | Android reference, `SensorEvent` | https://developer.android.com/reference/android/hardware/SensorEvent | D |
| A-ITS | Android CTS, camera ITS tests | https://source.android.com/docs/compatibility/cts/camera-its-tests | X |
| AZURE | Microsoft Learn, Document Intelligence Read model, input requirements | https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/prebuilt/read | D |
| TESS | Tesseract documentation, "Improving the quality of the output" | https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html | X |
| INOUE | Inoue, "Context-Independent OCR with Multimodal LLMs: Effects of Image Resolution and Visual Complexity", arXiv 2503.23667 (single-author preprint) | https://ar5iv.labs.arxiv.org/html/2503.23667 | X |
| URB | Urbanski and Peters, "Quantifying the Effects of Image Degradation on LVLM Benchmark Results Systematically", DATA 2025 | https://www.scitepress.org/publishedPapers/2025/134628/pdf/index.html | X |
| OCRR | Cheng, Wu, Chang, "How Robust is OCR-Reasoning? ...", arXiv 2606.26041 | https://arxiv.org/abs/2606.26041 | X (abstract only) |
| RUS | Rusiñol, Chazalon, Ogier, "Combining Focus Measure Operators to Predict OCR Accuracy in Mobile-Captured Document Images", DAS 2014 | https://l3i.univ-larochelle.fr/app/uploads/sites/12/2024/05/das14-focus-camera-ready-2013-12-19-a_PREPRESS.pdf | D |
| OAI | OpenAI API guide, images and vision | https://developers.openai.com/api/docs/guides/images-vision | X |
| FENG | Feng et al., "Evaluating OCR Performance for Assistive Technology: Effects of Walking Speed, Camera Placement, and Camera Type", arXiv 2602.02223 (preprint) | https://arxiv.org/html/2602.02223v2 | X |
| ARIA | De Mathia and Moreno-García, "Scene Text Detection and Recognition 'in light of' Challenging Environmental Conditions using Aria Glasses Egocentric Vision Cameras", arXiv 2507.16330 | https://arxiv.org/html/2507.16330v1 | X |
| RDTAG | ICDAR 2024 Competition on Reading Documents Through Aria Glasses, competition page | https://ilocr.iiit.ac.in/icdar_2024_rdtag | X (page); the report PDF is over the tool's size limit: N |

Not fetched and therefore not used: the Osaka head-mounted reading paper (ICDAR 2013; host did not resolve), Gandhi
et al., "Beyond OCRs for Document Blur Estimation" (ICDAR 2017; certificate error), Kumar, Ye, Doermann's dataset
paper and the Ye-Doermann survey (search listings only), SmartDoc-QA, and a NeurIPS 2025 paper on hallucination in
degraded documents (search listing only).

## 1. Handheld burst photography in low light

### What the three systems do

| Step | HDR+ (HDRP; details via IPOL, secondary) | Night Sight (LIBA, NSBL) | Multi-frame super-resolution (WRON) |
|---|---|---|---|
| Exposure | [S, HDRP abstract] One fixed exposure for all frames, set low enough to keep highlights; no bracketing, which makes alignment more robust. [S, IPOL] 2 to 8 frames by scene brightness. | [S, LIBA §2] "Motion metering": the motion of the scene and the hand is measured from pairs of viewfinder frames (a bounded optical-flow magnitude, 90th percentile per bin, centre weighted), a mixture model over the last samples predicts the least motion likely in the coming frames, and the exposure is the blur budget divided by that motion (their Eq. 6: t = B / v). Gain goes up first as light falls, then exposure and gain together. Up to 333 ms a frame handheld and 1 s when the gyroscope says the camera is braced; 6 to 13 frames in about 6 s of capture. [S, NSBL] up to 15 frames handheld on the product. | [S, WRON §3] A burst of raw frames from the zero-shutter-lag buffer; 15 frames merged. No exposure policy of its own. |
| Gyroscope | [NF] | [S, LIBA §2.3] Used to decide whether the camera is stable enough for longer exposures: angular speed averaged over about 1.5 s before the shutter press, leaving out the last 0.4 s. The motion measurement itself is from images. The value of the blur budget B, the stability threshold, and a reason for flow over the gyroscope are [NF]. | [S, WRON §4] Used only to characterise hand tremor (8,686 bursts: one standard deviation of rotation is about 0.9 px), which is what supplies the sub-pixel offsets. |
| Reference frame | [S, IPOL] The sharpest of the first three frames, sharpness being gradient magnitude in one green channel; the first three to limit shutter lag. | [S, LIBA §3.1] The sharpest frame of the burst. Blur in the reference stays in the result, because nothing deblurs. | [S] One base frame, all others aligned to it; how it is chosen is [NF]. |
| Alignment | [S, IPOL] Tiles matched coarse to fine on a 4-level pyramid of the 2x2-averaged Bayer image; L2 at coarse levels (computed with FFTs), L1 at the finest; a quadratic fit for sub-pixel steps except at the finest level. | [S, LIBA §3.1] The same, with tiles of 16, 32 or 64 px by noise level: larger tiles in darker scenes. | [S, WRON §3.2] The HDR+ alignment, then three Lucas-Kanade iterations for sub-pixel accuracy; a quadratic fit of the block-matching error was tried and found too inaccurate. |
| Merge | [S, IPOL Eq. 10-11] Per 16x16 tile, half overlapped, raised-cosine window, in the Fourier domain: each alternate tile is pulled toward the reference by A = D^2 / (D^2 + c sigma^2), D the difference from the reference and sigma^2 the noise variance from a shot-plus-read model. Large difference: the reference is kept. Small: a plain average. | [S, LIBA §3.2] The same merge with the constant c scaled per tile by a mismatch measure from the alignment error, so that static tiles are averaged harder in dark scenes; then spatial denoising that is stronger where less was merged. | [S, WRON §5] Kernel regression: every sample of every frame is added to the output pixel under a Gaussian kernel whose shape follows the local structure tensor (long along an edge, short across it), times a robustness weight, and the sum is divided by the sum of weights (Eq. 1). Kernel width grows with noise. |
| Rejection | In the merge: a tile that differs is not merged at that frequency. | Same, plus the mismatch map. | [S, WRON §5.2] A per-pixel weight from the colour difference to the base frame against the expected noise (Eq. 5), lowered where the alignment field is irregular, then eroded over 5x5. Rejected places fall back to one frame and are noisier. |
| Speed | [S, HDRP abstract] About 4 s for 12 MP on a phone, written in Halide. | [S, LIBA] Capture about 6 s; processing time [NF] in what was read. | [S, WRON] About 100 ms per 12 MP frame on a phone GPU (OpenGL ES shaders). |

One more statement that bears on this system: [S, LIBA §6.1] the zero-shutter-lag frames are not used at night
because the viewfinder limits their exposure and, at that length, read noise dominates. Short frames are not free.

### What applies here

- [I] The exposure policy is the part this system lacks. It records every page at 30 ms whatever the head is doing.
  LIBA's rule (exposure = blur budget / measured motion) can be driven by the gyroscope this system already samples
  at 200 Hz; no optical flow is needed because the scene is a still page and the motion is the head's.
- [I] The reference-frame rule transfers directly: the frame every other frame is laid against should be the
  stillest of the first few by the gyroscope, not the clip's first usable frame.
- [I] The tile merges of HDR+ and Night Sight exist to survive scene motion. A page is rigid, so one map per frame
  (as built) covers what tiles cover there; what this system could take from them is the robustness weight, for
  the places where a map is slightly wrong (the double edges seen in-house).
- [I] Larger alignment windows for darker frames (LIBA) is the same finding as the in-house one that textbook phase
  correlation fails on these frames and a band-passed correlation against the running sum works.

### What numpy on a phone can do in seconds

[I] throughout; none of the sources ran numpy on a phone.

| Part | Cost in numpy | Verdict |
|---|---|---|
| Exposure from gyroscope speed; stillest reference frame | A few hundred floating-point operations a page | Free. Runs on the glasses. |
| Per-frame global shift or homography | As built (about 24 s a clip for 60 frames) | Already the main cost. A gyroscope-predicted starting map (section 3) should remove coarse search levels. |
| HDR+ style tile merge | A batched FFT over about 47,000 half-overlapped 16x16 tiles a 3 MP frame, twice | Tens of seconds for 60 frames. Not worth it for a rigid page. |
| WRON kernel regression per sample | Nine anisotropic weights per sample per frame | Too slow per frame. As a single pass over the finished page (smoothing along strokes) it is one or two seconds. |
| Fourier accumulation (section 2) | One FFT pair per frame used; whole frame or 128 px blocks | Feasible for the frames added, of the order of the present cost. |

## 2. Lucky imaging and Fourier-domain merging

- [S, FBA Eq. 3] Fourier Burst Accumulation takes the registered frames' Fourier transforms and averages them with a
  weight per frame and per frequency: w_i = |v_i|^p / sum_j |v_j|^p. p = 0 is the plain average; p to infinity
  keeps, at each frequency, the frame with the largest magnitude. The magnitudes are smoothed with a Gaussian before
  the weights are taken (the unsmoothed transforms are what is averaged). All real-data results use p = 11.
- [S, FBA] The argument: a blur kernel is non-negative and sums to one, so it can only lower a frequency's
  magnitude. Hand shake differs from frame to frame, so each frame keeps different frequencies. The larger
  magnitude is the less blurred one.
- [S, FBA] Stated requirements: frames registered to the first by one homography each (found from SIFT matches; the
  paper says inertial sensors could do it instead); a static scene; additive white noise; kernels of small
  support. With registration errors of about 2 px or more a lower p is to be used; the best p in simulation was
  7 to 30, narrowing to 7 to 20 at about 1 px of registration error.
- [S, FBA] Noise: there is no denoising step. A larger p gives up noise averaging for sharpness. An optional
  sharpening after a denoiser is described and was left out of the comparisons.
- [S, FBA] Reported gain: sharper than the plain average while keeping its noise reduction, and better than
  lucky-frame selection (the best single frame stays noisier; averaging the best few adds blur). These are visual
  comparisons; no numbers for real bursts are given in what was read. Run time: a few seconds in Matlab for bursts
  of about a dozen frames.
- [S, FBAV] The video version registers neighbours by optical flow with a consistency check, works on 128x128
  half-overlapped blocks (so the weights are local), uses 7 frames, and takes about 15 s per HD frame in Matlab,
  two thirds of it in the optical flow. It states that it fails when the frames are blurred alike (a steady pan).
- Evidence for text: [NF] as an evaluation. [S, FBA, FBAV] Text appears only in passing (a word on a book spine,
  a sequence of books), as a place where competing methods fail.
- [S, PARK §4-5] The same idea with the kernels known from a gyroscope: the optimal linear estimate (their Eq. 5)
  weights each frame at each frequency by its kernel's conjugate transform over the summed squared magnitudes plus
  a noise term. Their Figure 2 shows eight consecutive handheld kernels with different power spectra and the
  average spectrum filling in as frames are added; with two or more frames the result is no longer destroyed by
  noise at the missing frequencies.

What applies here:

- [I] Head smear is close to a straight line during 30 ms. A frame smeared 4 px along one direction is intact
  across that direction and intact along it up to the first zero of its kernel (one cycle per 4 px). The present
  rule drops that frame entirely. On the in-house restless pages 97% of the frames are dropped; most of those are
  smeared 7 to 8 px, where detail along the motion is lost up to the size of a stroke and only detail across it
  survives.
- [I] The blind form (FBA) is a poor fit as published, for one reason: a single frame here has a level over noise
  of about 4.5 (in-house). At stroke frequencies its spectrum is mostly noise, so weights taken from single-frame
  magnitudes would be near equal and the method would fall back to the plain average of blurred frames. The paper
  assumes frames clean enough for their magnitudes to mean something.
- [I] The non-blind form fits: the gyroscope gives each frame's kernel (direction and length), so the weights come
  from the kernels and not from the noisy pictures. This is PARK's Eq. 5 with line kernels.
- [S, PARK §6-9] Cost and limits of that route: their implementation took 24.5 s for eight 5 MP frames on a CPU,
  10.5 s of it gyroscope drift correction, on 36x24 image blocks; align-and-average is the cheaper choice
  wherever it gives enough quality, and deconvolution wins when read noise dominates or the gain is already at
  its maximum.
- [S, FBAV] The method does not help when the frames are blurred alike. [I] A head that sweeps steadily along a
  line of text gives exactly that: every frame loses the same direction, and no weighting brings it back.

## 3. Using the gyroscope

### Timestamps

- [S, A-RES] `SENSOR_TIMESTAMP` is the start of exposure of the first row of the sensor's active array, in
  nanoseconds, the same value on every buffer of that capture.
- [S, A-RES, A-META] With `SENSOR_INFO_TIMESTAMP_SOURCE` = REALTIME it is in the time base of
  `SystemClock.elapsedRealtimeNanos()` and can be compared with other subsystems on that base. With UNKNOWN it is
  monotonic and comparable only with other captures of the same camera, not with the accelerometer or gyroscope.
- [S, A-SENS] A sensor event's timestamp is the time the event happened, in the `elapsedRealtimeNanos()` time base,
  increasing for a given sensor.
- [S, A-ITS] The CTS sensor-fusion test rotates the device in front of a checkerboard and requires the offset
  between camera and gyroscope timestamps to be under 1 ms. It is skipped when there is no gyroscope or the
  timestamp source is not REALTIME.
- [I] So the documentation promises alignment only for a REALTIME camera on a device that passed that test. Whether
  the glasses report REALTIME, and whether their firmware was held to the test, is not known from documents. It has
  to be read from the device and the offset measured (PARK estimate it per capture, below).

### Blur and alignment from rotation

- [S, PARK Eq. 3] For a camera that only rotates, a pixel moves by the homography K R K^-1, K the intrinsic matrix
  (mainly the focal length in pixels) and R the rotation integrated from the gyroscope over the interval. The blur
  kernel of a frame is the path that mapping traces during the exposure window.
- [S, MUST] The same model per row: the blur vector at a pixel is the mapping between the start and the end of that
  row's exposure. For short exposures the path is taken as a straight segment.
- [S, PARK §7.2] What goes wrong: the gyroscope's bias drifts. Their sensor's noise (0.21, 0.12 and 0.17 degrees a
  second, one standard deviation per axis) moved the predicted position by more than a pixel when the whole capture
  was longer than a sixth of a second. There is also an unknown delay between image and gyroscope time. They
  estimate bias, delay and rotation centre for every capture by comparing gyroscope-predicted kernels with the
  images, starting from the sharpest frame; with eight frames taken over 2 s the uncorrected drift was visible in
  the kernels.
- [S, PARK §8] With short exposures the frames are too noisy for that estimation to be accurate: their real-data
  curve falls below simulation at short exposure times for exactly this reason.
- [S, PARK, MUST] Translation is ignored; this holds for distant scenes or pure rotation.
- [I] For this system: the head turns about the neck and the camera sits about 10 cm from that axis, so a turn of
  10 mrad also moves the camera about 1 mm sideways. At a page 40 cm away that is 2.5 mrad of apparent shift, a
  quarter of the rotation's own effect, and it changes with distance. A gyroscope-only map will therefore be a
  few pixels off after a large move. It is a starting point for the image-based map, not a replacement.
- [I] Drift is not a problem at the scale used here if the gyroscope is integrated only between consecutive frames
  (about 45 ms) and across the 30 ms of one exposure; it would be if integrated across a whole clip.

### Rolling shutter

- [S, A-RES] `SENSOR_ROLLING_SHUTTER_SKEW` is the time between the start of exposure of the first row and of the
  row after the last, for the full active array; for a typical rolling shutter it equals the frame readout time.
  When the output covers N of the H rows, the value is to be scaled by N/H.
- [S, PARK Eq. 17; MUST] Each row's exposure window starts later by (row / rows) x readout time; with a gyroscope
  sampled faster than the frame rate, each row gets its own slice of the gyroscope record.
- [I] Consequences here, with an assumed full-array readout of 33 ms (the real value has to be read from the
  device): the centre crop of half the rows is exposed over about 16 ms from top to bottom. At 0.145 rad/s the
  bottom of the crop is displaced about 4 px against the top; at 0.035 rad/s, the speed at which a 30 ms exposure
  smears 2 px, about 1 px. A homography cannot represent that shear exactly. For frames chosen as still it is at
  the level of the present smear limit; for moving frames it is larger than the 0.5 px registration residual
  measured in-house, and any use of moving frames (section 2) has to time each row.
- [I] The first row of the centre crop starts a quarter of the full skew after `SENSOR_TIMESTAMP`. The gyroscope
  window used to judge a frame should be that row's start to the last crop row's end, not timestamp to timestamp
  plus exposure.

### Triggering at still moments

- [S, LIBA §2.3] Stability from the gyroscope decides whether longer exposures are allowed.
- [S, A-META] Android's motion-tracking capture intent caps exposure at 20 ms on devices that offer it, to limit
  blur for stabilisation and augmented reality. Whether the glasses list that capability is not known.
- [S, RUS §I] The document-capture literature proposes evaluating quality during capture so that the shot can be
  triggered when conditions are best, or the user directed.
- [NF] A published evaluation of gyroscope-gated or gyroscope-selected frames. A search returned a patent
  application and an app's manual, neither read.

## 4. Exposure time against number of frames; gain

### The model

- [S, HAS10 Eq. 2-3] Per pixel, with Phi the photo-electron rate, t the exposure and g the gain (electrons per
  digital number): three independent noise sources, photon noise of variance Phi t, read noise added before the
  amplifier, and conversion noise added after it. Referred to electrons, SNR^2 = (Phi t)^2 / (Phi t + s_read^2 +
  s_adc^2 g^2). Dark pixels are in the additive regime (SNR rises in proportion to light); bright ones in the
  photon regime (square root).
- [S, HAS10 §3] Raising ISO lowers g, so the after-amplifier term shrinks: for the same light collected, a higher
  ISO has a higher SNR in the dark parts, at the price of earlier saturation. The possible gain is 10 log10(1 +
  s_adc^2 g_max^2 / s_read^2); for the cameras in their Table 1 it is 2 to 20 dB.
- [S, HAS10 Eq. 7] For frames merged with optimal weights, SNR^2 adds: it is linear in the number of frames of a
  setting. With unequal exposures, each frame is weighted by its exposure squared over its noise variance (Eq. 6).
- [S, PARK Eq. 1] The same model, with read noise before and after analog gain, for a burst.
- [S, PARK Table 1] For n frames of exposure t each, merged with the blur known:

  | | No blur | Large blur |
  |---|---|---|
  | Read noise dominant | SNR grows as sqrt(n) x gain x t | sqrt(n) x gain x sqrt(t) |
  | Photon noise dominant | sqrt(n t) | sqrt(n): a longer exposure gains nothing |

- [S, PARK §5] The noise amplification of deconvolution grows linearly with exposure once consecutive kernels are
  uncorrelated, which they found beyond about 50 ms for handheld tablets.
- [S, PARK §6.2] For align-and-average there is an upper bound on exposure (the blur stays in the result) and a
  lower bound (frames too noisy cannot be aligned). The authors' advice: "AA is preferred to MD because the former
  has lower computational cost", when a setting exists at which it is good enough.

### What Android exposes

- [S, A-RES] `SENSOR_SENSITIVITY` is the gain applied before processing, in ISO units. At or below
  `SENSOR_MAX_ANALOG_SENSITIVITY` only analog amplification is used; [S, A-CHAR] above it the gain may be a mix of
  analog and digital.
- [S, A-RES] `CONTROL_POST_RAW_SENSITIVITY_BOOST` is a further digital gain applied after the RAW data is captured.
  It affects YUV and JPEG outputs only; their total sensitivity is sensitivity x boost / 100, and RAW stays at the
  sensor sensitivity. It takes effect only with auto-exposure off.
- [S, A-RES] `SENSOR_NOISE_PROFILE` gives, per colour channel of the raw image, the two coefficients of the noise
  model N(x) = sqrt(S x + O), x the signal normalised to 0..1. Where present it is the device's own statement of
  shot and read noise at the current gain.
- [S, A-RES] `SENSOR_FRAME_DURATION`: the frame rate of a session is governed by the largest stream configured in
  it, whether or not a request uses that stream; the minimum for each size and format is in
  `getOutputMinFrameDuration`.

### What that implies for 15, 30 and 60 ms here

All [I], built on two in-house numbers: one frame's level over noise was 2.2 at 10 ms and 4.5 at 30 ms (noise
reduction off, the dark scene). Whether gain and processing were identical in the two is taken on trust.

- The ratio 4.5 / 2.2 = 2.05 lies between pure photon noise (sqrt(3) = 1.73) and pure additive noise (3). Fitting
  HAS10's formula gives an additive noise equal to the photon noise of about 7 ms of exposure at that light (5 to
  10 ms within the rounding of the two inputs). At 30 ms about a fifth of the noise variance is additive; at 10 ms
  over two fifths.
- Per-frame level over noise relative to 30 ms, and frames needed for the same sum:

  | Exposure | One frame, relative | Frames for the same result | Head speed at which smear reaches 2 px |
  |---|---|---|---|
  | 60 ms | 1.5 | 0.45x | 0.018 rad/s |
  | 30 ms | 1 | 1x | 0.035 rad/s |
  | 15 ms | 0.65 | 2.3 to 2.5x | 0.070 rad/s |
  | 10 ms | 0.49 | 4.2x | 0.105 rad/s |
  | 7.5 ms | 0.40 | 6.4x | 0.14 rad/s |

  The last column uses about 1,900 px per radian, taken from the in-house pair of 0.12-0.145 rad/s giving 7-8 px
  in 30 ms; it should be replaced by the calibrated focal length.
- So at a fixed frame rate 15 ms wins only where it makes more than about 2.4 times as many frames still. On the
  in-house good pages (four frames in ten still at 30 ms) it cannot: 2.4 x 40% is not available. On the restless
  pages (5 to 8 of 290) it very likely does. If the frame rate can be doubled along with halving the exposure, the
  bar drops to about 1.2 times and 15 ms wins on nearly every page, at twice the frames to store and place.
- 60 ms is the mirror image: it needs under half the frames, but its still limit (0.018 rad/s) is below the
  0.04 rad/s of the calmest worn pages, which is what was seen in-house.
- At 21 to 24 frames a second with 30 ms exposures, the sensor is exposing 63 to 72% of the time. A frame duration
  equal to the exposure would collect 1.4 to 1.6 times the light per second with no change to the smear of any
  frame.
- The recorded gyroscope traces of the worn passes answer the 15-against-30 question without wearing the glasses
  again: slide a window of each exposure length (plus the crop's readout skew) along the trace and count the
  windows under the limit.

## 5. Legibility thresholds for machine reading

| Finding | Source | Mark |
|---|---|---|
| A commercial OCR service gives a minimum text height of 12 px for a 1024x768 image, which it equates to about 8 pt text at 150 dpi; images up to 10,000 px a side. | AZURE | S |
| Tesseract's documentation recommends at least 300 dpi and points to a user's test of the best capital-letter height; it states no pixel number itself and says nothing on blur. | TESS | S |
| Single jōyō kanji (100 sampled, one Mincho font, rendered large and reduced): two multimodal LLMs of early 2025 matched a conventional OCR service at about 40 px a character and fell below it under about 20 px; tested at 40, 20, 15 and 10 px. Exact accuracies are only in a figure. Some characters were misread at every size, including simple ones. Visual complexity correlated only weakly with errors. | INOUE | S |
| The API guide of the model family used here says that small text should be enlarged, that rotated text may be misread, and that performance may be lower for non-Latin scripts, naming Japanese. | OAI | S |
| SAT pages at 300 dpi, Gaussian blur of radius 1 to 7 px, noise with dimming, perspective; seven levels each, one degradation at a time; three models. All tolerated low levels; errors rose steeply near the top levels; noise with dimming hurt less than blur or perspective within the tested range; the strongest model at the worst blur still matched the weaker ones unblurred. No thresholds in numbers; the noise parameters are not reported. Models sometimes paraphrased instead of transcribing. | URB | S |
| A 2026 benchmark (812 samples, five perturbations at three severities, 18 models) reports that accuracy on clean images does not predict robustness, and that charts and tables degrade more than running text. | OCRR (abstract) | S |
| On 175 phone photos of 25 documents with focus blur, a combination of four cheap focus measures (gradient family) correlated with OCR accuracy at a median 0.94 within a document; computed over all images at once the correlation was 0.65. Two failure cases: a page with much white space scored low but read above 90%; a page with a large sharp headline scored high but read at 25%. | RUS | S |
| Minimum character height for kanji with classical OCR engines. | | NF |
| A controlled study of JPEG quality, or of H.264/HEVC bit rate, against OCR or LLM reading accuracy. A search returned only anecdotes and studies of other tasks. | | NF |
| A document-quality measure validated as a predictor of an LLM's reading accuracy. | | NF |

What applies here:

- [I] The in-house character pitch of 19 to 24 px in the sensor's pixels sits at the size where INOUE saw LLM
  reading begin to fail, and INOUE's images were clean. That agrees with the in-house finding that the same page
  read far better at twice the size, and with OAI's advice. It also means there is no margin: the wide lens and the
  reading distance set the pitch, and noise and smear come on top.
- [I] INOUE measured isolated characters; exam text has context, which helps recognition and also produces the
  plausible wrong words seen in-house. The two effects cannot be separated from the literature.
- [I] RUS explains the in-house observation that no simple measure separated the unreadable photos from the rest:
  such measures rank versions of one page well and rank different pages badly. They suit choosing between two
  gatherings of the same clip (a smear limit, a kernel), not gating a page.
- [I] URB's ordering (blur worse than noise at the levels they tried) and the in-house smear results point the same
  way, but URB's noise levels are unreported and the in-house level-over-noise results show a hard floor, so no
  trade-off between the two can be read from it.

## 6. How the vision API resizes images (short)

- [S, OAI] Current models count an image in 32x32 px patches, ceil(width / 32) x ceil(height / 32). Each model and
  detail level has a patch budget; an image over the budget is scaled down in proportion to fit. The guide lists,
  for the current families, a "high" level of up to 2,500 patches within about 2048 px a side, and an "original"
  level that keeps the image's dimensions up to a far larger limit (10,000 patches and 6,000 px a side on one
  family; up to a 30,000-patch rejection limit on the newest), and recommends "original" for OCR-like work.
  Smaller images are never enlarged.
- [I] A gathered page of 3024x4032 is 11,970 patches. Under a 2,500-patch budget it would be reduced to about
  46% (1,382x1,843), which turns a 40-48 px character pitch on the fine grid back into 18-22 px. A strip of
  3024x800 is 2,375 patches and passes unreduced. The cut into strips that the Codex route already makes is
  therefore what keeps the gathered pixels; a strip taller than about 830 px at full width would lose them under
  that budget.
- [NF] Which detail level and budget the ChatGPT web page and the Codex CLI apply to an attached image. The guide
  covers the API only. The table as extracted did not show a row for the exact model named in the project record.

## 7. RAW bursts against processed YUV

- [S, HDRP abstract] HDR+ starts from Bayer raw frames, not from the processor's output, for more bits per pixel
  and to avoid the processor's tone mapping and spatial denoising.
- [S, IPOL] Further reasons given: the noise model of raw data is known (variance linear in signal), and merging
  each colour plane separately avoids mixing channels.
- [S, LIBA, WRON] Both merge raw frames; WRON replaces demosaicing altogether by merging onto each colour's grid.
- [S, A-META] The RAW capability guarantees `RAW_SENSOR` output at the full pixel array and the metadata to
  interpret it. It states no frame rate.
- [S, A-META] The burst capability guarantees full-size YUV at 20 frames a second or more (10 or more in one case
  tied to the image size; see the reference for the exact condition), with exposure and white-balance locks, and
  says that RAW10, RAW12, RAW14 and Y8, where supported, come at the same rate as the largest YUV. `RAW_SENSOR` is
  not in that list.
- [S, A-MAP] `RAW_SENSOR` and JPEG are formats that may always have a stall duration: a request using them can hold
  back the next exposure. YUV_420_888 and PRIVATE never stall.
- [S, A-RES] The post-RAW boost does not reach RAW buffers.
- [I] For this system: the in-house finding that the video output is smoothed whatever is asked is the processor
  behaviour HDR+ avoids by using raw. The YUV frames copied by the app (noise reduction off) already avoid most of
  it, and they pass through 8 bits and an encoder. A raw route would have to be RAW10 to hold the rate, would
  deliver the full array (the crop is the app's work, which in-house cost 22.5 ms a frame in Java and heat), and a
  2016x1512 crop in RAW10 is 3.8 MB a frame, 2.4 frames a second at the 9 MB/s the glasses write. It is a route
  for a few frames, or for adding on the glasses, not for 60 frames a page as files.

## 8. Head-worn and body-worn capture; cueing the user (brief)

- [S, FENG] Signs, not documents: one walker, a phone on the head, shoulder or in the hand, and one pair of
  consumer camera glasses. Character accuracy fell with walking speed (0.50 at 0.8 m/s to 0.17 at 1.8 m/s) and with
  viewing angle; the three placements did not differ significantly; the glasses' camera read far worse than the
  phone's main camera in every condition (static: 0.38 against 0.97 with the best engine). Lighting was uniform
  indoor light. Motion blur was not quantified.
- [S, ARIA] Research glasses, scene text at 0.5 and 1 m: resolution dominated; one recogniser failed outright at
  the lower resolution at 1 m; enlarging those images before recognition cut the character error rate from 0.65 to
  0.48; lighting showed no consistent effect in a small data set; brightening dark images made errors slightly
  worse. Reading was restricted to a region around the wearer's gaze point.
- [S, RDTAG page] A 2024 competition on reading documents through research glasses names low resolution as the
  first difficulty, with pose, lighting and occlusion. Results are in a report that could not be fetched.
- [S, NSBL] The phone product tells the user to hold still after the shutter press and to brace the phone.
- [NF] A study of document pages captured in dim light by a head-worn camera with accuracy measured against known
  text; a study of how to cue a wearer to hold the head still, or of how long a wearer can.
- [I] The published work agrees with the in-house record on two points and adds nothing beyond them: on glasses the
  pixels per character are the first limit, and enlarging before reading helps. None of it addresses darkness.

## Ranked design changes

Order: first what recovers frames lost to head motion (a), then the 0.67 (b), then darkness (c), then the rest.
Within each, cheapest decisive step first. "Confirm" names the in-house measurement; those marked *offline* need
only the recordings already kept.

### (a) Frames lost to head motion

**1. Let the gyroscope run the clip: wait for stillness, show the wearer, end on light gathered and not on frame
count.**
- What: before and during a page, compute smear per exposure window from the gyroscope. Show one cue while the
  head is too fast. Count only still exposures toward the page; end the clip when the target is reached (about 50
  still 30 ms frames for a level over noise of 32 from 4.5 a frame, in-house arithmetic) or a time cap passes.
  Take the stillest early frame as the one others are laid against.
- Expected gain: on restless pages, from 5-8 usable frames toward the target, if the wearer responds; nothing on
  calm pages. [I]
- Cost: none on the phone; negligible on the glasses; seconds of the wearer's attention per page; clips of
  variable length (storage and send time grow on restless pages).
- Sources: LIBA §2 (exposure and capture budget from measured motion; gyroscope for stability; sharpest reference),
  NSBL (the product asks the user to hold still), RUS §I (trigger or guide at capture), PARK §6.2.
- Confirm: *offline*, replay the kept gyroscope records of the second worn pass and report, per page, the time
  until 50 still windows exist; then one worn pass with the cue.

**2. Choose the exposure per page from head speed, and close the gap between frames.**
- What: exposure = blur budget / angular speed over the last half second (LIBA's Eq. 6 with the gyroscope),
  quantised to 30, 15 or 8 ms, with the frame duration set to the exposure as far as the stream allows. Merge
  frames of different exposure with HAS10's weights.
- Expected gain: [I] a 15 ms frame is worth 0.65 of a 30 ms one, so 15 ms pays where it makes more than 2.4 times
  the frames still at the same frame rate, or more than 1.2 times at double the rate; restless pages should clear
  that, calm ones only with the higher rate. Closing the duty cycle alone (63-72% now) is up to 1.4-1.6 times the
  light per second at 30 ms.
- Cost: more frames to store, send and place for the same result (2.3-2.5 times at 15 ms); the 9 MB/s write limit
  forces fewer bits a frame or shorter clips; a faster stream heats the glasses more (in-house); alignment gets
  harder as frames get noisier (PARK §8, LIBA's larger tiles).
- Sources: LIBA §2.4, HAS10 Eq. 3 and 6-7, PARK Table 1 and §6.2, A-RES (`SENSOR_FRAME_DURATION`), A-META (the
  20 ms cap of the motion-tracking intent as a documented point of comparison).
- Confirm: *offline*, still-window counts at 30, 15 and 8 ms on the kept gyroscope records. On the desk, level
  over noise of one frame at 8, 15 and 30 ms at fixed gain to check the fitted 7 ms; the frame rate reached with
  frame duration set to the exposure and no larger stream in the session; forty pages for heat. Then a known page
  read twelve times per setting.

**3. Stop discarding smeared frames: merge them with weights from the gyroscope's blur.**
- What: for frames between the still limit and about three times it, form each frame's line kernel from the
  gyroscope (per row, with the readout skew), and add the frames in the Fourier domain with each frame weighted at
  each frequency by its kernel's transfer (PARK Eq. 5; FBA is the blind version of the same weighting).
- Expected gain: [I] the only route that uses frames now dropped. How many fall in the usable band on restless
  pages is not known until the traces are counted: typical smear there is 7 to 8 px. Bounded by PARK Table 1: with
  large blur the result grows as sqrt(n) and not with exposure. FBA reports results sharper than the average with
  the average's noise reduction, without numbers. No gain when the head moves the same way in every frame (FBAV).
- Cost: an FFT pair per added frame (of the order of the present 24 s a clip, more if in blocks); needs the
  camera-gyroscope offset, the focal length and the readout time known to well under a frame; registration error
  must stay near 1 px (FBA). PARK's own implementation took tens of seconds for eight frames.
- Sources: PARK §3-7, FBA §3 and its stated limits, FBAV (local blocks), MUST (per-row kernels).
- Confirm: *offline* on the PC with the ten worn clips of the second pass and their gyroscope records: gather (i)
  as now, (ii) with all frames under 6 px of smear weighted this way; compare at the page's own pixels and by
  three reads each. Do this before any phone work; if (ii) does not read better on the restless pages, drop it.

**4. Start every frame's map from the gyroscope, and judge stillness over the rows actually exposed.**
- What: predict the frame-to-frame map as K R K^-1 from the gyroscope between the two frames' mid-exposure times,
  then refine against the page as now. Take each frame's smear window from the first crop row's start to the last
  crop row's end.
- Expected gain: [I] fewer coarse search levels (time) and fewer lost frames after large moves; a truer stillness
  figure (the readout skew adds up to about 1 px at the present limit if the readout is near 33 ms).
- Cost: small. Needs three numbers measured once: focal length in pixels, camera-gyroscope time offset, readout
  skew.
- Sources: PARK Eq. 3, Eq. 14-15 and Eq. 17, MUST, A-RES (`SENSOR_TIMESTAMP`, `SENSOR_ROLLING_SHUTTER_SKEW`),
  A-META (timestamp source), A-ITS (1 ms on tested devices).
- Confirm: read the timestamp source and the skew from the glasses' capture results (read-only). *Offline*, on
  the kept clips, regress the image-found shifts between consecutive frames on the gyroscope-predicted ones: the
  slope is the focal length, the lag of best fit is the offset, the residual is what translation leaves.

### (b) The 0.67 of pages laid by a map

**5. Treat the 0.67 first as a property of the measure, then smooth the laid page with a normalised kernel.**
- What the number is: [I] the shift path shares each sample between the two nearest cells each way by distance;
  the map path puts it whole into the nearest cell (as the code reads on this date). For samples falling at
  random within a cell, sharing multiplies the single-cell noise by 2/3 in two dimensions. (Per axis a cell then
  draws on twice as many samples with shares of mean 1/2 and mean square 1/3, so its variance is (1/3) / (2 x 1/4)
  = 2/3 of the nearest-cell one; 4/9 for both axes; 2/3 in standard deviation. For frames all at one offset the
  factor depends on that offset, from 1/2 to 1.) That is the observed 22 against 32 and the factor of about 1.5
  in the code's own comment. Sharing also blurs slightly and makes neighbouring cells' noise correlated, so the
  two figures are not the same quantity.
- [S, DRIZ] This is the known behaviour of drop-size choices when frames are added on a finer grid: the nearest-
  cell limit is interlacing, the full-pixel limit is shift-and-add, a larger drop lowers the noise measured in
  one output pixel and correlates it with its neighbours, and the single-pixel figure then understates the noise
  on larger scales by a factor the paper gives in closed form (1.66 for a drop of 0.6 pixel on a grid of 0.5).
- So: (i) compare the two paths after the same low-pass, or after summing 2x2 cells, before calling it a loss of
  light; (ii) for the reader, divide a smoothed sum by a smoothed weight on map-laid pages (a 3-tap tent each
  way, or a Gaussian of about half a frame pixel), which also fills thinly covered cells from their neighbours;
  (iii) as an option, make that kernel long along strokes and short across them, from the page's own gradient
  tensor (WRON §5.1).
- Expected gain: [I] the level-over-noise figure returns to the shift path's scale by construction. Whether the
  model reads better is not known from any source; on the 2x grid everything above the frame's own Nyquist
  frequency is noise at this light (WRON: at low signal the gain of merging is denoising, not resolution), and
  the nearest-cell page keeps all of it.
- Cost: one pass over the finished page, not per frame; a second or two in numpy for 12 MP. Sharing inside the
  laying step instead would be four scattered adds a frame.
- Sources: DRIZ (noise section, Eq. 9-10), WRON Eq. 1 and §5.1, the code's `_Planes.add` and `_Planes.lay`.
- Confirm: *offline*: gather a desk clip with a known text twice, by the shift path and by the map path forced
  on, then the map path with (ii); level over noise after an identical low-pass; twelve reads each. The same on
  worn page 4, three reads each. This separates the measure from the reader in one sitting.

**6. Weight down the places where a frame's map is wrong.**
- What: per region of each laid frame, a weight from its difference to the page so far against the expected noise
  (WRON Eq. 5-9; LIBA's mismatch map), instead of one accept-or-reject per frame.
- Expected gain: [I] removes double edges where a map holds in the middle only; no gain where maps are good.
- Cost: one low-resolution comparison per frame, small beside the map search.
- Sources: WRON §5.2, LIBA §3.2.
- Confirm: *offline*, the worn clips whose pages were double at the edges before the per-frame map; edge sharpness
  at the page's own pixels with and without.

### (c) The venue's darkness

**7. Gather more still light per page; this is change 1 seen from the light's side.**
- [S, HAS10 Eq. 7] The squared signal-to-noise ratio adds over frames; nothing in the literature read offers a
  substitute for exposure time when one frame is at 4.5 and the reader needs 32. Changes 1 to 3 decide how much
  of the recorded time counts.

**8. Put all the gain where it lowers noise: analog to its maximum, digital only to fill the 8 bits.**
- What: set the sensor sensitivity to `SENSOR_MAX_ANALOG_SENSITIVITY` and no higher, and use the post-RAW boost
  only as far as the 8-bit output needs (in-house: under about 5.5 on this stream).
- Expected gain: [S, HAS10] the after-amplifier noise term falls with the square of the gain reduction factor;
  2 to 20 dB across the cameras in their table. [I] Unknown for this sensor, and zero if the present clip already
  runs at the analog maximum.
- Cost: none.
- Sources: HAS10 §2-3, PARK Eq. 1, A-RES (`SENSOR_SENSITIVITY`), A-CHAR (`SENSOR_MAX_ANALOG_SENSITIVITY`), A-RES
  (post-RAW boost).
- Confirm: on the desk, one frame's level over noise at sensitivity 100, 200, 400, 800 with the boost adjusted to
  keep the product constant, values read back from the capture results; and the sensor's own noise profile if it
  reports one.

**9. A few RAW10 frames of the looked-at part, only if 8 and the YUV route leave a measurable gap.**
- Expected gain: [S, HDRP abstract] more bits and none of the processor's denoising; [I] the size of the gain over
  YUV frames with noise reduction off is unknown, and the in-house gap between direct YUV frames and the encoded
  clip is about one point of characters wrong.
- Cost: 3.8 MB a frame after the app's own crop, a Java pass per frame, heat, memory (in-house: full-size stills in
  a row exhausted it); `RAW_SENSOR` may stall and has no rate guarantee, RAW10 has one only with the burst
  capability.
- Sources: HDRP, IPOL, WRON, A-META, A-MAP.
- Confirm: on the desk, the mean of 20 RAW10 crops against the mean of 20 YUV crops at one exposure and gain: level
  over noise and twelve reads. Not before 1 to 8.

### The rest

**10. Keep what was gathered on its way into the model.** Send parts no larger than the model's patch budget at
the detail level in force (2,500 patches is, for example, 3024x800), and ask for the level that keeps dimensions
where the route allows it. Sources: OAI; INOUE for why 40 px a character matters. Confirm: where the route reports
image tokens, compare with ceil(w/32) x ceil(h/32) times the model's factor for one strip; otherwise read one page
as strips of two heights.

**11. Use a focus measure only to compare versions of one page.** A gradient-energy figure on the gathered page can
choose between smear limits or kernels for the same clip without spending reads; it should not gate pages. Source:
RUS (0.94 within a document, 0.65 across). Confirm: *offline*, rank the gatherings from 3 and 5 by it and check the
ranking against their reads.

## What was not found

- The full text of the HDR+ paper and of Karpenko et al. could not be fetched; HDR+ is described here from its
  abstract, from Night Sight's paper and from a published re-implementation.
- The value of Night Sight's blur budget in pixels, its stability threshold, and its reason for measuring motion
  from images.
- Any evaluation of Fourier accumulation, or of gyroscope-known deconvolution, on text.
- Any published study of selecting or triggering frames by gyroscope stillness.
- A minimum character size for kanji with classical OCR; the one quantitative source for LLMs is a single-author
  preprint on isolated characters in one font.
- Any controlled measurement of JPEG, H.264 or HEVC compression against OCR or LLM reading accuracy, and any
  quality measure validated against an LLM reader.
- A frame-rate guarantee for `RAW_SENSOR`; how the ChatGPT web page and the Codex CLI resize attachments.
- Document capture by a head-worn camera in dim light with accuracy against known text; how to cue a wearer to
  hold still and how long one can.
