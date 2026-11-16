# Capture practice: what shipping products, vendor documentation and practitioners do (2026-11-16)

Status: Research. Product documentation, vendor developer documentation, open-source scanner code and practitioner
write-ups read on 2026-11-16. Nothing in this file was run on the glasses or the phone, and no repository code was
changed. Every in-house number quoted here comes from the project record as it stood that day and is labelled
"in-house"; it was not re-measured. This file is the practical companion of
`docs/capture-accuracy-research-2026-11-16.md` (the academic side and Android's camera2 reference) and does not
repeat it; where a point rests on that file it says "accuracy note".

## How to read this file

Each statement carries one of four marks.

- **[S1]** from the source (first-party): the vendor's own documentation, help page, engineering blog or source code.
- **[S3]** from the source (third-party): a reviewer, an integrator, a community document, a paper about someone
  else's product, or a copy of a manual hosted by someone else.
- **[I]** inference (mine): arithmetic or reasoning that joins a source to this system. Not in any source.
- **[NF]** not found: looked for and not found, or the page could not be fetched.

The "Read" column of the source table says how each source was read.

- **D** read directly (page text, source file or PDF pages seen as they are).
- **X** read through the fetch tool's extraction by a small model. Check a number against the source before a
  design depends on it.
- **L** search listing only: the search tool's summary of the page. Weakest; nothing is asserted beyond the
  listing, and every use below says "listing".
- **N** not fetched. Nothing about its contents is asserted.

All URLs were read on 2026-11-16. Search results were thin for several questions; each section says where.

## Sources

| Id | Source (kind) | URL | Read |
|---|---|---|---|
| MLKD | Google ML Kit, document scanner overview and Android guide (vendor documentation) | https://developers.google.com/ml-kit/vision/doc-scanner and `/android` under it | D |
| MLKT | Google ML Kit, text recognition v2 for Android, input image guidelines (vendor documentation) | https://developers.google.com/ml-kit/vision/text-recognition/v2/android | X |
| APLS | Apple Support, scanning documents on iPhone (product help) | https://support.apple.com/en-us/108963 | X |
| APLV | Apple, `VNDocumentCameraViewController` reference | https://developer.apple.com/documentation/visionkit/vndocumentcameraviewcontroller | N (the tool received a title and no body) |
| LENS | Microsoft Support, Microsoft Lens for iOS (product help) | https://support.microsoft.com/en-us/lens/microsoft-lens-for-ios | D |
| ADBE | Adobe Scan for Android help, "Scan" (product help) | https://www.adobe.com/devnet-docs/adobescan/android/en/scan.html | D (first 9,000 characters) |
| SBFQ | Scanbot SDK documentation, "How can I avoid capturing blurry images?" (vendor documentation) | https://docs.scanbot.io/faq/how-to-avoid-blurry-images/ | D |
| SBRN | Scanbot React Native SDK 7.1.1, `configurations.ts`, the parameters' own comments (vendor source code) | https://app.unpkg.com/react-native-scanbot-sdk@7.1.1/files/src/base/configurations.ts | X |
| GSBL | Genius Scan SDK v6, blur detection (vendor documentation) | https://geniusscansdk.com/docs/v6/document-scanning/blur-detection/ | D (start of the page); the levels' wording L |
| GSQS | Genius Scan SDK v5 Android API, `QuadStreamAnalyzer` and its `Status` (vendor API reference) | https://geniusscansdk.com/docs/v5/android/api/ (class `com.geniusscansdk.core.QuadStreamAnalyzer`) | X |
| DYNA | Dynamsoft developer blog, an Android document scanner with auto-capture (vendor tutorial) | https://www.dynamsoft.com/codepool/android-document-scanner.html | X |
| WESC | WeScan (open-source iOS scanner), `RectangleFeaturesFunnel.swift` (source code) | https://raw.githubusercontent.com/WeTransfer/WeScan/master/Sources/WeScan/Scan/RectangleFeaturesFunnel.swift | D (first 8,000 characters) |
| ONS | Open Note Scanner (open-source Android scanner), `ImageProcessor.java` (source code) | https://raw.githubusercontent.com/allgood/OpenNoteScanner/master/app/src/main/java/com/todobom/opennotescanner/ImageProcessor.java | X |
| DBX1 | Dropbox tech blog, fast and accurate document detection for scanning, 2016 (the product team's engineering blog) | https://dropbox.tech/machine-learning/fast-and-accurate-document-detection-for-scanning | X |
| DBX2 | Dropbox tech blog, on the responsiveness of the document detector (engineering blog) | https://dropbox.tech/machine-learning/improving-the-responsiveness-of-the-document-detector | X |
| JHMK | Jack Henry developer documentation, remote deposit best practices, describing Mitek MiSnap (an integrator's documentation; second-hand for MiSnap) | https://api.payments.jackhenry.com/docs/rda-ws/DeveloperTools/BestPractices | X |
| MBDS | Microblink BlinkID web SDK, `DetectionStatus` | https://docs.microblink.com/blinkid-web-sdk/type-aliases/DetectionStatus | L (404 on fetch) |
| PSCN | Google Research blog, "PhotoScan: Taking Glare-Free Pictures of Pictures", 2017 (engineering blog) | https://research.google/blog/photoscan-taking-glare-free-pictures-of-pictures/ | X |
| ENVS | Envision support, "Scan Text" for Envision Glasses (product help) | https://support.letsenvision.com/hc/en-us/articles/7603550797713 | D (characters 0 to 14,500) |
| ENVA | AFB AccessWorld, review of Envision Glasses (third-party review) | https://www.afb.org/aw/23/11/18109 | X |
| ORCR | OrCam help, "How do I read text with the OrCam Read" (product help) | https://orcam.helpjuice.com/2714239-how-do-i-read-text-with-the-orcam-read | X |
| ORCM | OrCam MyEye guides | several | L |
| SEEA | App Store listing of Seeing AI, written by Microsoft (product description) | https://apps.apple.com/us/app/seeing-ai/id999062298 | X |
| SEET | The Chicago Lighthouse, "Seeing AI Tips for Voice Over Users" (third-party tips sheet, PDF, 4 pages) | https://chicagolighthouse.org/wp-content/uploads/2019/09/Seeing-AI-B.pdf | D |
| KNFM | KNFB Reader manual, a copy hosted by a third party | https://vipconduit.com/terry/info/KNFBReaderManual.htm | X |
| LOOK | Google Accessibility help, Lookout (product help) | https://support.google.com/accessibility/android/answer/9031274 | X |
| CUTT | Cutter and Manduchi, "Towards Mobile OCR: How To Take a Good Picture of a Document Without Sight", DocEng 2015 (evaluation with 12 blind participants) | https://escholarship.org/uc/item/9p9902m4 | D (pages 1 to 7 of 9) |
| CUT2 | Cutter and Manduchi, "Improving the Accessibility of Mobile OCR Apps Via Interactive Modalities", TACCESS 2017 | DOI 10.1145/3075300 | L |
| ROKO | Rokid's own pages: the store's product page, the global product page, the open platform and the SDK documentation portal | https://store.rokid.com/products/rokid-glasses, https://global.rokid.com/products/rokid-glasses, https://open.rokid.com/, https://custom.rokid.com/prod/rokid_web/57e35cd3ae294d16b1b8fc8dcbb1b7c7/pc/us/index.html | N (HTTP 429 on every attempt at the product pages; the two portals returned a title and no body) |
| RKCM | `buildwithfenna/rokid-docs`, community documentation of the glasses' system, partly from decompiled firmware; states it is not affiliated with Rokid (third-party) | https://github.com/buildwithfenna/rokid-docs (yodaos/docs/apps/camera2.md (a path in that other repository), yodaos/docs/development/hardware-features.md (a path in that other repository)) | README X; the two files D |
| RKRV | Reviews and retailer pages giving Rokid Glasses camera figures | several | L |
| LEOP | Leopard Imaging, datasheet of a camera module built on the Sony IMX681 (a module maker's datasheet) | https://leopardimaging.com/wp-content/uploads/2025/10/LI-IMX681-MIPI-AF-96D_Datasheet.pdf | D (page 2) |
| DXOM | DXOMARK, "AI-Powered SmartGlasses: Why Camera Quality Matters for Text Recognition" (third-party test laboratory) | https://www.dxomark.com/ai-powered-smartglasses-why-camera-quality-matters-for-text-recognition/ | X |
| MIXD | mixed-news, an article quoting Meta's Wearables Device Access Toolkit documentation (third-party report of first-party documentation) | https://mixed-news.com/en/meta-dat-camera-720x1280-lower-resolution-higher-quality/ | X |
| METD | Meta, Wearables Device Access Toolkit, Android integration page (vendor documentation) | https://wearables.developer.meta.com/docs/develop/dat/build-integration-android/ | X (holds no camera figures) |
| VUZX | Vuzix support, M400 and M4000 camera (vendor developer documentation) | https://support.vuzix.com/docs/camera | D |
| BFRM | Brilliant Labs, Frame hardware manual (vendor documentation) | https://docs.brilliant.xyz/frame/hardware | X |
| RMA | Rachel Ma, "Building OCR for smart glasses", 2026 (practitioner write-up; employer not stated) | https://sayrachel.substack.com/p/building-ocr-for-smart-glasses | X |
| GCV | Google Cloud Vision, supported files (vendor documentation) | https://docs.cloud.google.com/vision/docs/supported-files | X |
| TXQ | Amazon Textract, set quotas; and best practices (vendor documentation) | https://docs.aws.amazon.com/textract/latest/dg/limits-document.html, https://docs.aws.amazon.com/textract/latest/dg/textract-best-practices.html | D |
| ABBY | ABBYY FineReader Engine and Vantage image recommendations | several | L (403 and 404 on fetch) |
| AREQ | Android reference, `CaptureRequest`: `CONTROL_AE_ANTIBANDING_MODE`, `CONTROL_VIDEO_STABILIZATION_MODE` | https://developer.android.com/reference/android/hardware/camera2/CaptureRequest | X (three passes over the page) |
| APST | Android Open Source Project, camera preview stabilization | https://source.android.com/docs/core/camera/camera-preview-stabilization | X |
| GYRF | Gyroflow documentation, common filming tips (the documentation of an open-source stabiliser) | https://docs.gyroflow.xyz/app/getting-started/common-filming-tips-and-issues | X |
| NIKN | Nikon Z 9 online manual, video flicker reduction (camera maker's manual) | https://onlinemanual.nikonimglib.com/z9/en/15_menu_guide_03_21.html | X |
| ANTV | Anthropic, vision guide (vendor documentation) | https://platform.claude.com/docs/en/build-with-claude/vision | D (searched in the page text) |
| GEMI | Google, Gemini API image understanding (vendor documentation) | https://aistudio.google.com/docs/image-understanding (redirected from ai.google.dev) | X |
| OLMO | Poznanski et al., "olmOCR: Unlocking Trillions of Tokens in PDFs with Vision Language Models", arXiv 2502.18443 | https://arxiv.org/html/2502.18443 | X (first 100,000 characters) |
| OMNI | OmniDocBench, arXiv 2412.07626 | https://arxiv.org/html/2412.07626 | X |
| SASA | Sasagawa, Kurita, Kawahara, "Evaluating Multimodal Large Language Models on Vertically Written Japanese Text", arXiv 2511.15059 (LREC 2026) | https://arxiv.org/html/2511.15059v1 | X |
| ZHAN | Zhang et al., "MLLMs Know Where to Look", ICLR 2025, arXiv 2502.17422 | https://arxiv.org/abs/2502.17422 | X (abstract only) |
| GDLT | GDELT Project blog, shrinking video frames before OCR, 2024 (practitioner measurement) | https://blog.gdeltproject.org/?p=22332 | X |
| DCAM | FamilySearch, Dcam user guide, capturing large documents (an archive's operating guide for its own capture software) | https://www.familysearch.org/en/fieldops/article/dcam-user-guide-capturing-images-large-documents | X |
| PANO | Panotools wiki, photography guidelines (the wiki of the Hugin and Panorama Tools community) | https://wiki.panotools.org/Photography_Guidelines | X |
| GEM3 | Gemma 3 "pan and scan" (technical report and library documentation) | several | L |
| JURV | Jürviste and Jakobson, vision LLMs for historical dictionaries, arXiv 2510.07931 | https://arxiv.org/abs/2510.07931 | X (abstract only) |
| NPFF | NumPy reference, discrete Fourier transform | https://numpy.org/doc/stable/reference/routines.fft.html | X |
| SPFF | SciPy, FFT tutorial; `scipy.fft.rfft2` reference | https://docs.scipy.org/doc/scipy/tutorial/fft.html, https://docs.scipy.org/doc/scipy/reference/generated/scipy.fft.rfft2.html | X |
| TMXO | Termux packages: the OpenCV recipe and its Python subpackage; the `python-scipy` recipe directory (packaging source code) | https://github.com/termux/termux-packages (x11-packages/opencv/build.sh (a path in that other repository), x11-packages/opencv/opencv-python.subpackage.sh (a path in that other repository), `packages/python-scipy/`) | D |

Not fetched and therefore not used beyond what is said of them: Apple's panorama help page (title and no body),
the OpenCV documentation site (HTTP 403 on three pages), Stearns et al. on haptic against auditory guidance (PDF
not decodable by the tool and not opened), the NFB article on KNFB Reader 3.0 (the part read holds no capture
detail), GoPro's own support pages (a search returned only third-party guides), Scanbot's quality-analyzer page
(the code sample did not render, so its parameters were not obtained).

## 1. Document-scanner products and SDKs: when they capture, what they check, what they tell the user

### What is published

| Product | When it captures by itself | Checks after capture | What the user is told | Mark |
|---|---|---|---|---|
| Google ML Kit document scanner | Lists automatic capture with document detection among its capabilities. No parameter is exposed: page limit, gallery import, scanner mode and result format are the only options. The whole flow, models included, is delivered by Google Play services, and the device needs at least 1.7 GB of memory. | Not described. | Not described. | [S1, MLKD] |
| Apple document camera | In Auto mode the document is scanned without a press once it is in view; otherwise the shutter or a volume button. | The user drags the corners afterwards. | Only to place the document in view of the camera. | [S1, APLS]; developer reference [NF, APLV] |
| Microsoft Lens | Manual in the page read: the user checks that an orange frame outlines the item and presses the button. | Crop and filters afterwards. | The orange frame; for screen-reader users, spoken directions such as "move right". The same page says Lens was being retired from iOS in early 2026. | [S1, LENS] |
| Adobe Scan | Auto-capture is the default. Live boundary detection marks the document's corners with dots; the app captures once it can see the whole document. | Automatic crop and cleaning, then a review screen with retake. | Three messages in order: looking for a document; "Capturing... hold steady" once edge detection sees the entire document; and, when no edges are found, a prompt to capture by hand. | [S1, ADBE] |
| Scanbot SDK | A detection status is computed for every preview frame. A photo is taken when the status is good and a delay has run: the sensitivity setting runs from 0 (wait 3 s) to 1 (at once), default 0.66, which the comment gives as 2 s. Accepted only if the document fills at least 80% of the screen's width or height (default) and its perspective score is at least 75 of 100 (default); a brightness threshold on a 0 to 255 scale decides "too dark" (no default shown). | A "document quality analyzer" grades each scan in five steps from very poor to excellent; the vendor recommends at least the middle grade and otherwise sending the user to retake. | One configurable hint per status: fine; too small; bad angles; bad aspect ratio; off centre; orientation mismatch; too dark; too noisy; nothing detected. | [S1, SBRN, SBFQ] |
| Genius Scan SDK | A stream analyzer moves through four states: not found, searching, about to trigger, trigger; a minimum time between the last two exists (its value is not on the page read). | "Readability" detection for focus blur and motion blur, tuned for text documents and weaker on pages with little text or textured backgrounds. The integrator sets a required level; a scan below it raises a retake prompt on the review screen. | The retake prompt. A listing describes the warning as advisory, never blocking. | [S1, GSQS, GSBL]; last sentence L |
| Dynamsoft (tutorial) | A "quad stabilizer": the outline found in consecutive frames must overlap the previous one by an intersection-over-union of at least 0.85 with an area change of at most 0.15, for 3 frames in a row; then 1.5 s of cooldown before the next capture. | None in the tutorial (no blur test). | None beyond a "no document" notice. | [S1, DYNA] |
| WeScan (open source) | Rectangles from the last 8 frames are compared; one is shown when at least 3 lie within 40 px of each other; a counter rises each time the best rectangle lies within 6 px of the one displayed, and the scan fires when it passes 35. | None in this file. | The drawn rectangle. | [S1, WESC] |
| Open Note Scanner (open source) | One frame is enough: Canny edges (thresholds 75 and 200) on a frame reduced to 500 px of height, the largest four-cornered contour, all corners inside a "hot area". No stability over frames. | No blur or focus measure. | A green outline on the found page; a pale guide area. | [S1, ONS] |
| Mitek MiSnap, as an integrator describes it | Works on the video stream and captures only when a suitable frame is found. | On the device, before anything is sent: focus, brightness, skew, object size, glare and corners, each against a threshold. The thresholds are not published there. | Real-time feedback until a frame passes, including a notice for a low-contrast or cluttered background. | [S3, JHMK] |
| Microblink BlinkID | Detection status values include camera too far, camera too close, angle too steep, document too close to the frame edge, document partially visible. | Not read. | Not read. | L only (MBDS) |
| Dropbox scanner | The posts read cover detection, not the trigger. | Not covered. | A live outline. Detection ran at 8 to 10 frames a second on the phones of 2016 against a goal of 100 ms a frame; in between, the outline is carried from frame to frame by a cheap search over scale and shift after the gyroscope has taken out the roll, so that the outline is drawn at 30 Hz in step with the picture. | [S1, DBX1, DBX2] |

### What the table says

- [S1] Every product that publishes its trigger uses the same two conditions: the whole document is found, and it
  has stayed put for a dwell. The dwell is expressed as time (Scanbot: 0 to 3 s, default 2 s) or as consecutive
  agreeing frames (Dynamsoft: 3; WeScan: more than 35 increments at 6 px).
- [I] None of the published triggers measures motion with an inertial sensor; all infer stillness from the outline
  not moving in the preview. This system has the direct measure (the gyroscope at 200 Hz) and no outline that
  needs to hold still, so the products' dwell maps onto "enough still exposure gathered", not onto a timer.
- [S1] "Too far" is a first-class state in the two SDKs that publish states (Scanbot's too-small status with its
  80% default; Microblink's too-far value, listing only). It is judged from the outline's size, which needs the
  sheet's edges in view.
- [S1] "Too dark" is a state of its own in Scanbot, decided from brightness alone.
- [S1] Quality after capture is a separate step from the trigger wherever it exists (Scanbot, Genius Scan, MiSnap),
  it is specific to text (Genius Scan says so), and its result is a prompt to retake, not a silent rejection.
- [S1, MLKT] Google's on-device text recogniser gives the only published size rule among these products: "each
  character should be at least 16x16 pixels", with no accuracy benefit said to come from characters larger than
  24x24; poor focus is named as a cause of errors and the documented remedy is to ask the user to recapture.
- [NF] Published thresholds for blur, glare or focus in any shipping scanner. Apple, Google and Microsoft publish
  no parameters at all; Mitek's are behind a customer login according to the search; Scanbot's quality-analyzer
  parameters could not be read.
- [NF] Any published statement of how the stock products detect motion blur at capture time, as opposed to
  after it.

## 2. Guidance with little or no display: assistive reading products

Search results for first-party documentation were good for Envision, OrCam Read and Lookout, and thin for Seeing
AI and KNFB Reader (third-party copies only).

### What the products do

| Product (camera) | Framing and distance cue | Stillness cue | Capture | Mark |
|---|---|---|---|---|
| Envision Glasses, Scan Text (head-worn) | "Smart Guidance": the edges of the sheet are detected and a spoken command says which way to move it, for example "Move document left". The help page tells the wearer to hold the sheet at arm's length before the right eye, straight and not bent. A second mode, "Word Detection", plays taps whose rate rises with the number of words the camera sees; the wearer moves the sheet until the rate stops rising, then double-taps. The two modes cannot be on together. | The instruction to hold the sheet steady; nothing measured. | With Smart Guidance, automatic as soon as all four corners are in view, confirmed by a capture sound and then a processing sound. Manual capture plays a countdown sound first. | [S1, ENVS] |
| OrCam Read (handheld) | A projected laser frame or pointer shows on the paper what will be captured. Distance 15 to 35 cm. | The help page says to keep the text still, not to capture while walking, and to use a book stand if steadiness is hard. | On the trigger; a shutter sound, beeps while processing. Afterwards it announces if the text is upside down, the light too low, or the text unreadable. | [S1, ORCR] |
| OrCam MyEye (head-worn) | The wearer points a finger under the text; a double beep acknowledges; the device may say that the finger is not centred. About 30 cm from the face. | Not found. | Shutter sound; a chime when nothing was recognised. | L only (ORCM) |
| Seeing AI, document mode (handheld) | Spoken edge reports such as "bottom left edge not visible", and a too-close report; the user moves toward the missing edge. Paper at arm's length, phone at the chest. | Once all four edges are seen it tells the user to hold steady, and plays music for the few moments the hold lasts; the page is ready when the music stops. | Automatic at the end of the hold. | [S3, SEET]; that audio cues exist [S1, SEEA] |
| KNFB Reader (handheld) | A "field of view report" on request: which of the four edges are visible and how many degrees the page is rotated. "Tilt guidance": the phone vibrates in pulses, faster the further it is from level, silent when level. About 27 to 32 cm above an A4 page. | Hold still while the report is spoken. | An automatic mode takes the picture once text is detected and all four edges are in the frame. The flash fires by itself when the scene is too dark. | [S3, KNFM: a third-party copy of the vendor's manual] |
| Google Lookout (handheld) | Documents mode: hold in portrait, move slowly, follow real-time guidance to get the whole page. Text mode: move the text closer or away. | "Move slowly". | A snapshot button; the page notes that a snapshot can read better than the live view. | [S1, LOOK] |
| Microsoft Lens with VoiceOver | Spoken directions. | Not found. | Manual. | [S1, LENS] |

### What evaluations say

- [S3, CUTT] The one controlled study read in full. Twelve blind participants, a phone held over a letter-size
  sheet, camera pose measured from printed markers. A pose was "compliant" when all four corners of the printable
  area were visible and a lowercase letter of 12 pt text was at least 12 px tall. Two assisted modes were compared
  between groups: confirmation only (the user hovers, the system says "Pose compliant" when the pose is good) and
  guidance (in addition, spoken directions at most once a second, at most two axes at a time, the largest
  correction first, plus a prompt to level the phone).
  - Unassisted, seven of the twelve could not take a single compliant picture; non-compliant poses were mostly too
    close, and off-axis more than compliant ones.
  - Assisted, the mean time to a compliant pose was 13.9 s (medians per participant 3.6 to 48.1 s), and the
    difference between guidance and confirmation only was not significant.
  - After the assisted session, unassisted pictures were better: the median proportion of the page legible rose
    from 0.72 to 0.89 (p = 0.04), with no significant difference between the two modes.
  - Both groups rated the system easy to follow (median 5 of 5).
- [S3, CUT2, listing only] The later journal version is summarised as finding again no significant time difference
  between guidance and automatic capture, and a preference for continuous feedback over feedback on request.
- [S3, ENVA] A review of the Envision Glasses describes the two guidance modes and reports no measurement of them.
- [NF] A published evaluation of Envision's, OrCam's, Seeing AI's or Lookout's guidance, and any evaluation of a
  "hold still" cue as such.

### What carries over to a small visual mark

All [I].

- The cue that did the work in CUTT is the confirmation: one signal that says the pose is good now. Directions on
  top of it bought no time. That is the cheapest thing to show: one mark that appears when the page is being
  gathered and is absent otherwise.
- Envision's word-detection taps are a single rising quantity, steered by the wearer until it stops rising. On a
  display that is a short bar whose length follows how much text of sufficient size the camera sees. It needs no
  outline of the sheet and no known paper size.
- Seeing AI's music during the hold is a progress signal for the dwell: the user knows the hold has begun, that it
  is still running, and when it has ended. On a display: an arc that closes. This system's wearer has none of the
  three (in-house: no cue to hold still; the photo in hand appears only afterwards).
- Edge reports ("this edge is missing") become one arrow at the side where the paper leaves the recorded window,
  shown one at a time and no more often than once a second, as in CUTT.
- OrCam Read's laser frame answers "what exactly is being captured" on the paper itself. The glasses cannot
  project, but a fixed bracket on the display can stand for the recorded window if its place against the camera's
  centre crop is calibrated once; whether a monocular display can be registered well enough is not known.
- Spoken and haptic cues do not carry over as they are; the products rely on them because their users cannot see.
- KNFB's tilt cue has a direct counterpart that needs no camera: the gyroscope's rate as a "too fast" mark.

## 3. Smart-glasses cameras in practice

### This device

- [NF] Rokid's own documentation of the glasses' camera (capture sizes, video modes, stabilisation, exposure
  limits, recommended practice). Four first-party addresses were tried: the two product pages answered HTTP 429
  each time, and the open-platform page and the SDK documentation portal returned a title and no body to the
  fetch tool (they appear to be rendered by script). Nothing is asserted about their contents.
- [S3, RKCM] A community repository, which states it is unaffiliated and draws partly on decompiled firmware,
  lists the system's declared hardware features: among them `camera.full`, `camera.raw`, a gyroscope and an
  accelerometer. It describes the stock camera app as AOSP's Camera2 app with a direct-capture activity whose
  defaults are a 640x480 preview and a 4032x3024 still taken after 10 preview frames. It gives no measurement of
  the camera. In-house records already hold the measured equivalents (RAW offered; full-size stills); the
  repository adds nothing that was not measured.
- [S3, RKRV, listings only] Reviews and retailers give a 12 MP Sony IMX681 at f/2.25, stills of 3024x4032 and a
  109 degree diagonal field; they disagree on video (1680p at 30 or 60 frames a second, or 3K) and one mentions
  electronic stabilisation of video. None is a measurement of text capture.
- [S1 for the module, LEOP] A camera-module maker's datasheet for a module on that sensor: 1/3.6 inch format
  (5.04 mm diagonal), 1.0 um pixels, 4032x3024 active pixels, 30 frames a second at full size. [I] With the
  in-house 1.9 mm lens that is 1,900 px per radian, the figure the accuracy note derived from smear, if the
  sensor is indeed this one.
- [S3, DXOM] A test laboratory compared six camera glasses reading a printed chart at 40 cm under 1,000, 300 and
  20 lux, with one fixed prompt asking for exact transcription. "Rokid AI Glasses" scored highest for printed text
  in all three lights; the article attributes this, with the word "appears", to strong sharpening in that
  device's image pipeline, and concludes that the camera pipeline and not only the model decides reading. No
  scores, text sizes, mounting or scoring method are given, and the article does not say which Rokid model or
  whether the pictures came through an app's camera2 path or the vendor's own assistant. [I] It is the only
  published low-light reading comparison found, and 20 lux is a named condition a desk test can reproduce.

### Comparable devices

| Device | What is documented | Mark |
|---|---|---|
| Ray-Ban Meta through Meta's toolkit for third-party apps | Streams offered to apps are 720x1280, 504x896 or 360x640 at 2 to 30 frames a second, limited by the link to the phone; the documentation, as quoted, advises that a lower resolution and frame rate give better picture quality because less compression is needed. A photo call exists. | [S3, MIXD, quoting first-party documentation]; the first-party page read holds no figures [S1, METD] |
| Vuzix M400 and M4000 | Camera2 supported; stills up to 4032x3024; a centre-crop mode (1408x792) that uses only the sensor's central pixels and is recommended for barcodes, where the subject is small and centred; autofocus from 10 cm; optical stabilisation "to offset small movements caused by the operator wearing the camera", switched in system settings. | [S1, VUZX] |
| Brilliant Labs Frame | A 1280x720 sensor cropped to 720x720; gain and exposure under the app's control. | [S1, BFRM] |
| Mentra Live | Photo size options are documented inconsistently across pages. | L only |
| Even Realities G1 | Not searched to a source. | [NF] |

- [S3, RMA] A practitioner's account of building OCR for glasses names the failure causes as head movement, lens
  flare and occlusion, says that reducing images before recognition makes text too small to find, proposes
  cropping to the text instead, and says word-level recognition is not enough without grouping and reading order.
  No numbers, no employer stated.
- [I] The pattern across devices: an application rarely gets the sensor's full pixels over a stream; the device
  that documents a centre crop of native pixels (Vuzix) recommends it for exactly the small, centred subject. That
  is the form this system reached in-house (the centre of the field in the sensor's own pixels).
- [I] The one comparable head-worn device with a documented remedy for wearer motion uses an optical stabiliser.
  This device's lens is fixed (in-house), so motion can only be met by exposure time and by choosing frames.
- [NF] Community measurements of the Rokid Glasses camera on text (resolution charts, low-light reading, video
  stabilisation behaviour), and developer reports of reading printed pages with it.

## 4. Text at a distance and in low light, practical

### Pixels per character in vendor documentation

| Vendor | Statement | Mark |
|---|---|---|
| Google ML Kit (on-device) | At least 16x16 px a character; no benefit above 24x24; no separate figure for Chinese, Japanese or Korean. | [S1, MLKT] |
| Google Cloud Vision | 1024x768 recommended for text detection because recognition needs more resolution; no character size; images over 75 million pixels are reduced. | [S1, GCV] |
| Amazon Textract | Minimum text height 15 px, equated to 8 pt at 150 dpi; at least 150 dpi advised; do not convert or downsample a supported file before sending. Japanese is among the listed languages. Text is read when aligned horizontally; no vertical text is offered. | [S1, TXQ] |
| ABBYY | 300 dpi for text of 10 pt and above and 400 to 600 dpi for smaller text; one ABBYY product's FAQ recommends 400 to 600 dpi for Chinese, Japanese and Korean. | L only (ABBY) |
| Azure, Tesseract | In the accuracy note (12 px at 1024x768; 300 dpi). | accuracy note |

- [I] The vendors' minimums sit at 12 to 16 px of character height for Latin text, and the one that gives a
  comfortable upper figure says 24 px. The in-house character pitch worn (19 to 22.5 px; 24 on the desk page that
  passed) is inside that band for a classical recogniser of Latin text, and has no margin for kanji, noise or
  smear, which agrees with the in-house finding that the same page read better at twice the size.
- [I] What distance that is. At 1,900 px per radian a character pitch of p mm at d mm covers 1,900 p / d pixels.
  For a pitch of 3.7 mm (10.5 pt type, an assumption; the papers' real pitch should replace it): 17.6 px at 40 cm,
  23 px at 30 cm, 28 px at 25 cm. Reaching 24 px means the paper within about 29 cm of the camera. The reading
  distances the assistive products print (15 to 35 cm for OrCam Read, 27 to 32 cm for KNFB Reader on A4; their
  lenses are not this one's) are in the same range, and the laboratory test above used 40 cm.
- [NF] A vendor figure for the minimum size of Japanese characters, and any vendor statement for vertical
  Japanese text other than Textract's horizontal-only rule.

### Exposure rules for handheld and head-mounted cameras

- [S3, listings only] The photographers' reciprocal rule: handheld, expose no longer than one over the focal
  length in 35 mm terms. [I] For a 1.9 mm lens on a sensor of 5.04 mm diagonal the equivalent focal length is
  about 16 mm, so the rule would allow about 1/16 s, 60 ms. In-house, 60 ms worn left hardly a frame still. The
  rule is written for a picture looked at whole; this system needs the picture sharp at its own pixels, where
  the limit is head speed times exposure times 1,900 (accuracy note).
- [S1, GYRF] The stabiliser's documentation says of the film-makers' rule of exposing for half the frame interval
  "that rule doesn't work when using any kind of digital stabilization", because blur recorded in a frame stays
  and points the wrong way once the frame is moved; it recommends a quarter or an eighth of the frame interval
  and no neutral-density filter. [I] At 30 frames a second that is 4 to 8 ms: action-camera practice for a
  head-mounted camera is about four to seven times shorter than this system's 30 ms, and assumes daylight.
- [NF] First-party action-camera guidance on shutter time against motion blur (only third-party guides came
  up), and any published rule for a head-mounted camera reading text.

### Electronic stabilisation on Android

- [S1, AREQ] `CONTROL_VIDEO_STABILIZATION_MODE` warps frames to steady motion between consecutive frames and may
  change the crop region to do it. Where a device reports support, an output going to a recorder or a codec is
  guaranteed stabilised only up to 1920x1080 and 30 frames a second; at other sizes the result reports OFF. It
  takes several frames to start, should be set at session creation, and should not be combined with optical
  stabilisation.
- [S1, APST] Stabilisation of the preview and other non-RAW streams is a platform feature from Android 13, where
  the device maker implements it. [I] The glasses run Android 12, so only the older video mode can exist there.
- [I] For this system electronic stabilisation is the wrong tool even if the device lists it: it does nothing
  about blur within an exposure (GYRF says the same of every digital stabiliser), it resamples and crops the
  pixels the gathering wants untouched, and the in-house path copies the camera's YUV frames itself. Reading
  `CONTROL_AVAILABLE_VIDEO_STABILIZATION_MODES` once (read-only) would settle whether it is even on offer and
  that the clip session reports OFF.

### Flicker of indoor lighting

- [S1, AREQ] Some fixtures flicker with the mains (50 or 60 Hz by country); a wrong exposure time shows as
  flicker or as bands across the picture. With manual exposure the antibanding setting has no effect and "the
  application must ensure it selects exposure times that do not cause banding issues";
  `STATISTICS_SCENE_FLICKER` in the capture result reports what the device detects.
- [S1, NIKN] A camera maker's list of flicker-free times: 1/100, 1/50, 1/25 s under 50 Hz and 1/125, 1/60, 1/30 s
  under 60 Hz.
- [S3, listings only] Japan's mains are 50 Hz east of a line through the Fuji and Itoi rivers and 60 Hz west of
  it, with mixed districts near the line.
- [I] The in-house clip exposes 30 ms by hand. Light on 50 Hz mains pulses every 10 ms, so 30 ms is three whole
  pulses and every row gets the same light. On 60 Hz mains the pulse is 8.33 ms and 30 ms is 3.6 pulses: rows
  exposed at different phases differ in brightness, and the pattern moves from frame to frame. The nearest clean
  times there are 25.0 and 33.3 ms. The long form (60 ms) is clean at 50 Hz and 7.2 pulses at 60 Hz (58.3 ms is
  clean). Whether the venue's lamps flicker at all is unknown: many LED fixtures do not, some flicker far
  faster.

## 5. Preparing images for a vision LLM that reads documents

The accuracy note covers OpenAI's guide (patch budgets, "original" detail, small text to be enlarged, rotated and
non-Latin text as weaknesses) and three studies of degradation. This section adds what else was found.

- [S1, ANTV] Anthropic's guide: an image larger than the tier's limit is scaled down to fit, keeping its shape
  (its table shows 3840x2160 arriving as 1456x819 on one tier and as 2576x1449 on the high-resolution tier of
  newer models; the search listing gives the edge limits as 1,568 and 2,576 px). It asks for clear images, text
  that is legible and not too small, and adds: "Avoid cropping out key visual context solely to enlarge the
  text". It lists mistakes on low-quality, rotated or very small images as a limitation, and recommends
  introducing each of several images with a short numbered label so that they can be referred to.
- [S1, GEMI] Google's guide: images above 384 px a side are cut into 768x768 tiles of 258 tokens each; a
  `media_resolution` setting raises the tokens per image and is said to help with fine text at the price of time
  and tokens; images should be correctly rotated and not blurry.
- [S3, OLMO] A document-conversion model's paper renders pages to 1,024 px on the longest edge for fine-tuning,
  reports no test of resolution, and finds that supplying text extracted from the file beside the image helps
  general models (overall score 68.9 to 69.9 for one, 57.8 to 63.8 for another). Old scans were the hardest
  class for every system (best score 42.8 of 100). No de-skewing or binarisation is used or discussed.
- [S3, OMNI] A benchmark with page-level labels: on fuzzy scans the general models spread widely (edit distance
  0.082 for the best, 0.263 for GPT-4o, 0.15 for the best conventional pipeline); on text rotated by 270 degrees
  "Most models fail to recognize text when it is rotated 270 degrees" (0.718 for GPT-4o against 0.285 for a
  classical recogniser). It holds English and Chinese only and has no vertical-text label.
- [S3, ZHAN, abstract only] Accuracy of multimodal models on a question depends on the size of the thing asked
  about, shown as a causal effect; interventions that enlarge the relevant region without retraining raise
  accuracy on seven benchmarks.
- [S3, GDLT] A practitioner's test on a cloud OCR service (not an LLM): 1280x720 video frames reduced to boxes of
  500, 400, 300, 200 and 100 px; errors appear at 400 px for simple captions and already at 500 px for dense text
  and for a frame with vertical Chinese; nothing is read at 100 px.
- [NF] A measurement of binarisation, contrast stretching, sharpening or de-skewing against the reading accuracy
  of a current vision LLM. The search returned unsourced figures on marketing blogs and one anecdote; none is
  used. For classical OCR such steps are standard (accuracy note, Tesseract); for LLMs the vendors' guides ask
  only for upright, sharp, large-enough text.

### Japanese vertical text

- [S3, SASA] The one study found. Synthetic pages of Japanese text set both ways, one to four columns, and 100
  real pages with vertical text. Character error rates as its tables give them (some exceed 100, so they read as
  percentages), one column, raw output: GPT-4.1 1.88 horizontal against 18.2 vertical; GPT-5 2.09 against 21.3;
  open models from 0.1 to 8 horizontal against 7.6 to 128 vertical. On the real pages most models were above 65;
  a document-specialised model reached 20.1. Failure modes: one model family read vertical text in horizontal
  order; the others kept the order and misread more characters; models ran into repetition. Fine-tuning one open
  model on the synthetic pages removed the gap (0.10 vertical). The paper states no image resolution and did not
  test telling the model the direction, or turning the image.
- [S1, ENVS] The Envision help page advises switching its layout detection off for vertically written text.
- [S1, TXQ] Textract reads horizontally aligned text only.
- [I] The models named in SASA are older than the one this system uses, and its in-house readings of vertical
  pages (1.6 to 3.1% wrong on desk pages) are far better than SASA's figures, so the size of the effect does not
  carry over. The direction of the effect is a risk the in-house record has not measured: the same text set
  horizontally was never read for comparison, and worn photos of horizontal text are listed as unmeasured.
- [I] Sending strips cut along the lines, as the Codex route does, gives the model a few columns at a time and
  with them a short, unambiguous reading order; SASA's column-count result is too mixed to confirm or refute
  that this is why strips helped in-house.

## 6. Sheets larger than one frame

Search results were thin: no phone scanner was found that documents stitching a sheet from several shots.

- [S1, DCAM] An archive's capture guide for documents larger than the camera's field: fix the camera height,
  divide the sheet by a template into equal sections (quarters in the example), take the upper-left section
  first as the base image, go left to right and then down in a Z, overlap neighbours by about 7.6 cm, attach the
  other sections to the base image, and review that the whole sheet was captured. The page read does not say the
  sections are stitched.
- [S1, PANO] For stitching, the panorama community's wiki advises "Take photos with about 50% overlap" and says
  20 to 30% is enough for alignment alone; exposure and white balance are best fixed across the set.
- [S1, ADBE] Adobe Scan's book mode takes both pages of an open book in one landscape shot, shows a dotted line
  for the user to lay on the binding, and splits the shot into two pages there; a "straighten" step corrects page
  curvature and works even when one of the four boundaries is outside the picture.
- [S1, PSCN] Google's PhotoScan takes a reference frame and four more while the user moves the phone, aligns each
  to the reference by a homography from sparse features, then corrects what the homography cannot (a print that
  is not flat) with optical flow computed on a coarse grid, which cut that step's time by about 40 times on the
  phone, and takes a soft minimum across frames to remove glare.
- [S3, GEM3, listing only] One open model family's own remedy for large or oblong images is to cut the image into
  equal crops that do not overlap, encode each, and give them to the model together with the whole image.
- [S3, JURV, abstract only] A digitisation project fed a vision LLM overlapping tiles of each scanned page and
  had a second model merge the structured output; no comparison with and without tiling is in the abstract.
- [S1, ANTV] Several images in one request should each be introduced by a label.
- [NF] Guidance from any model vendor on giving a model several overlapping partial views of one page, and any
  measurement of overlap width against reading errors (duplicated or dropped lines at the seams).
- [I] What the sources add up to for this system: capture in a fixed order with a known count of parts, overlap
  by a quarter to a third so that a line cut by one part is whole in the next, keep the parts separate (stitching
  is a second registration problem and PSCN shows what it takes even for a flat print), send an overview of the
  whole sheet beside the labelled parts, and tell the model that neighbouring parts repeat text. In-house, the
  Chat route already splits a spread at the fold and the Codex route asks the model where the pages are; the
  missing piece is on the capture side, where a spread no longer fits one clip.

## 7. Speed on a phone

Search results were thin. No published timing of multi-frame alignment and merging in numpy or OpenCV on an ARM
phone was found; the timings in the accuracy note (a vendor pipeline in Halide, a GPU merge, a desktop
deconvolution) remain the only ones.

- [S1, NPFF] `numpy.fft` promotes single-precision input to double precision; its real-input transforms compute
  only the non-negative frequencies. The page points to SciPy for a transform that does not promote.
- [S1, SPFF] SciPy's FFT is fastest for lengths that are powers of two and slowest for primes, offers
  `next_fast_len` to choose a padded length, has real-input 2-D transforms, and takes a `workers` argument (or a
  `set_workers` context) for threads. The pages read do not state its single-precision behaviour.
- [S1, TMXO] Termux packages SciPy, and packages OpenCV 5.1.0 with a Python subpackage; the OpenCV recipe lives
  in the X11 package set and depends on Qt 6, OpenBLAS and FFmpeg among others.
- [S1, DBX2] The Dropbox scanner made its per-frame tracking cheap in two ways that apply to any alignment: the
  gyroscope removes one degree of freedom before the image search, and precomputed running sums make each
  candidate's score a constant-time lookup.
- [S1, PSCN] Computing the fine registration on a coarse grid and interpolating between grid points, instead of
  per pixel, was worth a factor of about 40 on a phone.
- [NF] First-party OpenCV documentation of which functions are NEON-accelerated (the documentation site refused
  the fetch tool); timings of `warpPerspective`, `remap`, `phaseCorrelate` or ECC alignment on phone-class ARM
  cores; a timing for an open-source HDR+ re-implementation (its README gives none).
- [I] For this system (the code as read on this date uses `np.fft.rfft2` and `irfft2` on single-precision
  arrays, a homography per frame, and index arithmetic to lay pixels): the transforms run in double precision
  whatever the input; whether a single-precision, threaded transform at padded sizes is faster on the phone has
  to be timed there. A profile by stage on one worn clip should come before any change, because none of the
  sources says where 24 s goes. The largest saving the sources point to is doing less: fewer frames per page
  once enough still light is in (accuracy note, change 1), and a search that starts from the gyroscope
  (accuracy note, change 4; DBX2).

## (a) Practices of shipping products that this system does not have

"Does not have" is as the project record describes the system on this date. The right-hand column is [I]
throughout.

| # | Practice | Who does it (source) | On a head-worn camera with a small monochrome display |
|---|---|---|---|
| 1 | A visible state sequence: searching, found, hold, done | Adobe Scan (ADBE); Genius Scan's four states (GSQS); Scanbot's per-frame status (SBRN) | One mark at a time in a fixed corner: open brackets while watching, closed brackets when a page is seen, an arc that closes while the clip gathers, a tick. No words. |
| 2 | A dwell the user can perceive, with its end signalled | Seeing AI's music during the hold (SEET); Scanbot's 0 to 3 s delay (SBRN); stability counters (WESC, DYNA); Envision's capture and processing sounds (ENVS) | The closing arc is driven by still exposure gathered, measured by the gyroscope, not by a clock: it stalls while the head moves and the wearer sees it stall. |
| 3 | A "too far" state | Scanbot's size score, default 80% (SBRN); Microblink (MBDS, listing); Lookout's closer-or-away (LOOK); CUTT's compliance rule of 12 px letters | Character pitch estimated from the preview's text lines, shown as a two-state distance mark (come closer; fine) or as a short bar. No sheet outline or paper size needed. |
| 4 | A single rising quantity the user maximises | Envision's word-detection taps (ENVS) | The bar of row 3 lengthening with the amount of text at sufficient size inside the recorded window. |
| 5 | A "too dark" state | Scanbot's brightness threshold (SBRN); OrCam Read's announcement (ORCR); KNFB's automatic flash (KNFM) | No flash exists here. The state changes the dwell instead: more still exposure is asked of a darker page, and the arc closes more slowly. |
| 6 | A direction to move, one at a time | Envision (ENVS); Seeing AI's edge reports (SEET); Lens with VoiceOver (LENS); KNFB's field-of-view report (KNFM); CUTT's guidance mode | One arrow at the side where the page leaves the recorded window, at most once a second. Lower priority: CUTT found no time gain over confirmation alone. |
| 7 | Showing what will be captured on the paper itself | OrCam Read's laser frame (ORCR); the orange frame of Lens (LENS); Adobe's corner dots (ADBE) | A fixed bracket standing for the centre crop, if the display can be registered to the camera once. Unverified. |
| 8 | A text-specific quality grade after capture, with a retake prompt | Scanbot's quality analyzer (SBFQ); Genius Scan's readability level (GSBL); MiSnap's on-device checks before sending (JHMK); ML Kit's advice to ask for a recapture (MLKT) | A "weak page" mark on the three-second review, decided on the glasses from what is known at once (still exposure gathered, gain), and the same verdict from the phone once the page is gathered. Advisory, as in Genius Scan. |
| 9 | Instruction on posture and support | OrCam Read: keep the text still, do not capture while walking, use a book stand (ORCR); Envision: arm's length, steady, sheet straight (ENVS); KNFB: a stated height over the page (KNFM) | A sentence in the operator's own procedure, not on the display: how to brace the head and where to hold the paper. |
| 10 | An outline or mark that keeps up with the picture | Dropbox: detection at 8 to 10 Hz, carried between detections with the gyroscope (DBX2) | Marks that depend on finding the page are updated from the gyroscope between the slower image measurements, so that they do not lag the head. |
| 11 | A protocol for sheets larger than the field | An archive's Z-order capture with fixed overlap and a final coverage check (DCAM); book mode with a split line (ADBE); dots to move to (PSCN) | Parts in a fixed order, a row of dots showing which part is next and which are done, an overview frame of the whole sheet, the parts kept separate. |
| 12 | A camera pipeline tuned for reading, separate from the one for photographs | DXOMARK's conclusion from six glasses (DXOM) | A reader's copy of the gathered page with its own sharpening, tested against the plain copy. In-house, sharpening a bright photo did not help once; a gathered page was not tried. |
| 13 | Exposure times tied to the mains frequency under manual exposure | Android's documentation leaves it to the app (AREQ); camera makers publish the times (NIKN) | The clip's exposure chosen from the detected flicker: 30 ms on 50 Hz, 25 or 33.3 ms on 60 Hz. |

## (b) Ten ranked changes drawn from those practices

Order: the wearer's motion first (most frames are lost there, in-house), then distance, then the page verdict,
then framing and large sheets, then light, reading, speed. "Check" names the in-house measurement; *offline*
needs only recordings already kept. Expected effects are [I] unless marked.

**1. Show the gathering as a state and a closing arc driven by the gyroscope.**
- What: rows 1, 2 and 5 of the table. The mechanism (still exposure counted from the gyroscope, the clip ending
  on light gathered) is change 1 of the accuracy note; what the products add is its form: a found state, a hold
  state whose progress is visible, an explicit end.
- Expected effect: on restless pages (in-house: 5 to 8 still frames of 290) the wearer learns within the page
  that the head is too fast, instead of afterwards or never. CUTT's result that a confirmation signal alone
  brought blind users to a good pose in a mean of 13.9 s, and improved their unaided pictures afterwards, is the
  nearest evidence that such a signal changes behaviour. [S3]
- Cost: display work on the glasses and one more consumer of the gyroscope; no phone work. Clips become variable
  in length.
- Sources: ADBE, SEET, SBRN, WESC, DYNA, GSQS, CUTT.
- Check: *offline*, replay the kept gyroscope records and draw the arc's progress against time for each page:
  how long would each page have taken to close. Then one worn pass in the order of use.

**2. Tell the wearer how to brace, and measure what bracing is worth.**
- What: row 9. A fixed posture for capture (for example elbows on the desk and the chin or temple on a hand, the
  paper raised toward the face instead of the head lowered to it), written into the procedure.
- Expected effect: unknown in size. In-house, pages differed by a factor of three in head speed (0.04 to 0.145
  rad/s) with no instruction given; the products that depend on a sharp picture all give one.
- Cost: none in software.
- Sources: ORCR, ENVS, KNFM; the accuracy note for the vendor's "brace the phone".
- Check: in the worn pass of change 1, two minutes of the gyroscope trace in each of two postures, pages turned
  as in use; compare the share of 30 ms windows under the smear limit. Needs the wearer; nothing on the desk
  stands in for it.

**3. A distance mark from the character pitch seen in the preview.**
- What: rows 3 and 4. Estimate the spacing of text lines in the watched frame (a one-dimensional transform of
  the brightness profile across the lines is enough), convert to character pitch, show "closer" below a
  threshold and "fine" above it.
- Expected effect: the wearer keeps the page where characters are 24 px or more (about 29 cm for 3.7 mm type by
  the arithmetic in section 4) instead of 19 to 22 px. In-house, the wearer could not tell the distance from the
  existing far mark.
- Cost: a small computation on preview frames on the glasses (heat to be watched); a threshold to set.
- Sources: MLKT (16 to 24 px), TXQ (15 px), SBRN (a size threshold as a default), ENVS (a quantity to maximise),
  CUTT (12 px as the compliance rule).
- Check: *offline*, run the estimate on the first frames of the kept clips against the pitch measured from their
  gathered pages (19 to 22.5 px in-house). On the desk, a page at 25, 30, 35 and 40 cm: estimate against truth,
  and the mark's switching distance.

**4. A verdict on each page before it is turned, and the same list before the answers.**
- What: row 8. On the glasses, at the end of a clip: was the target of still exposure reached. Mark the
  three-second review when it was not. On the phone: the gathered page's frame count and level over noise, with
  weak pages named before the answers (in-house, an ungathered page is already named).
- Expected effect: a restless page is retaken while the paper is still in hand. In-house, the page with a known
  text was among the restless ones in both worn passes.
- Cost: small; the quantities exist. A retake gesture already exists.
- Sources: SBFQ, GSBL, JHMK, MLKT.
- Check: *offline*, on the kept worn clips (the second pass's records hold the gyroscope's readings, the first
  pass's each frame's smear): does the count of still exposure windows alone separate the clips that gathered
  from those that did not.

**5. One arrow when the page is leaving the recorded window.**
- What: rows 6, 7 and 10. In-house, worn spreads lie below the frame's centre and the camera crops at its centre
  only. Show an arrow toward the page when its text mass is off the window, carried between image measurements
  by the gyroscope.
- Expected effect: fewer pages cut by the window. Smaller than changes 1 and 3: CUTT found directions no faster
  than confirmation alone.
- Cost: finding the text mass in the whole-field preview at a low rate; the same heat caution.
- Sources: ENVS, SEET, LENS, KNFM, CUTT, DBX2.
- Check: *offline*, how many of the kept worn clips have text cut by the window's edge; if few, drop this.

**6. A capture protocol for sheets larger than the window.**
- What: row 11 and the last paragraph of section 6. Parts in a fixed Z order with a quarter to a third of
  overlap, dots for progress, an overview frame, parts sent separately with labels and the overview, the model
  told that neighbours overlap.
- Expected effect: sheets that do not fit become capturable without stitching. No source measures the reading
  side.
- Cost: capture-side state for parts of a page; the prompt; the association of answers with a page made of
  parts.
- Sources: DCAM, PANO, ADBE, PSCN, ANTV; GEM3 and JURV as weaker support.
- Check: on the desk, a sheet with a known text in two and in four parts: the stand-in route first for the flow;
  then, as one of the operator's real runs when one is decided, parts with an overview against parts alone,
  counting lines dropped or doubled at the seams.

**7. Tie the clip's exposure to the mains.**
- What: row 13. Read `STATISTICS_SCENE_FLICKER`; expose 30 ms on 50 Hz, 25 or 33.3 ms on 60 Hz (58.3 ms for the
  long form).
- Expected effect: removes moving bands where the lamps flicker at twice the mains and the mains are 60 Hz;
  nothing elsewhere. Size unknown.
- Cost: negligible.
- Sources: AREQ, NIKN.
- Check: read-only, the flicker statistic in the capture results under the lights of use. On the desk under a
  mains-driven lamp, the spread of row means from frame to frame at 30 ms against 33.3 ms (or 25 ms).

**8. Measure the writing direction's effect once, and say the direction in the prompt.**
- What: section 5. Keep sending upright images (in-house already does). State in the prompt that the text is
  vertical and that columns and strips run right to left, with the strips labelled in that order.
- Expected effect: unknown; SASA shows a tenfold gap on older models and did not test a prompt.
- Cost: prompt text.
- Sources: SASA, OMNI, ANTV, TXQ, ENVS.
- Check: one known text typeset vertically and horizontally at the same pixels per character, rendered on the
  PC, read the usual twelve times each; then with and without the direction sentence. No device needed.

**9. Profile the gathering on the phone by stage, then try a single-precision threaded transform.**
- What: section 7. Time each stage for one worn clip; replace `numpy.fft` by SciPy's with padded lengths and
  workers where the profile says transforms dominate.
- Expected effect: unknown until profiled.
- Cost: a new dependency on the phone (packaged by Termux); the rule that a clip of glasses lying still gathers
  to the same page bit for bit would have to be re-based, since another transform rounds differently.
- Sources: NPFF, SPFF, TMXO, DBX2, PSCN.
- Check: on the phone, stage timings for a kept worn clip before and after; the twelve desk clips gathered both
  ways and compared at the page's own pixels.

**10. Try a sharpened reader's copy of the gathered page.**
- What: row 12. An unsharp mask on the finished page only, where the noise has been averaged down.
- Expected effect: unknown, possibly none: in-house a sharpened bright photo read no better, and DXOM's
  attribution is hedged.
- Cost: one pass over the page.
- Sources: DXOM.
- Check: *offline*, a desk-gathered page with a known text, plain against sharpened, twelve reads each.

## (c) What was not found

- Rokid's own documentation of the camera: every first-party address either refused the fetch tool or returned
  no body. No capture sizes, video modes, stabilisation or exposure limits are asserted from Rokid.
- Community measurements of this camera on text, and developers' reports of reading printed pages with it; the
  one laboratory comparison names a Rokid device without saying which and gives no scores.
- Published capture thresholds for blur, glare or focus in Apple's, Google's, Microsoft's, Adobe's or Mitek's
  scanners, and the parameters of Scanbot's quality analyzer.
- Any shipping scanner that documents using an inertial sensor for its capture trigger.
- An evaluation of a "hold still" cue, of Envision's, OrCam's, Seeing AI's or Lookout's guidance, or of any
  visual guidance mark on a head-worn display. The one study read in full is of blind users with a handheld
  phone; the study of haptic against auditory cues was not opened.
- A vendor's minimum size for Japanese characters; the ABBYY figures are from search listings only.
- First-party action-camera guidance on exposure against motion, and any exposure rule for a head-mounted
  camera reading text.
- A measurement of binarisation, contrast, sharpening or de-skewing against a current vision LLM's reading;
  whether a prompt that states the writing direction helps on vertical Japanese.
- Vendor guidance or measurements on giving a model overlapping partial views of one page; a phone scanner that
  documents multi-shot capture of one large sheet.
- Timings of multi-frame alignment or merging in numpy or OpenCV on phone-class ARM processors; first-party
  OpenCV documentation of its NEON paths (site not fetchable).
- Standards for camera capture of documents (for example archival imaging guidelines) were not searched.
