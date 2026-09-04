plugins {
    id("com.android.application")
}

// The glasses-side document scanner.
//
// This is what the 2026-09-04 capability spike selected. Measured on
// `RG-glasses` build 1.25.012-20260901-150201: camera2 opens and returns
// 4032x3024 JPEGs in 785-1380 ms, the glasses reach the server on their own
// Wi-Fi, a sideloaded app is launcher-visible, and KEYCODE_BACK is consumable.
// So the phone is not in the data path at all.
//
// Unlike `:glassprobe`, this one carries dependencies, and deliberately the
// same two the phone relay uses: the bundled Japanese ML Kit recognizer and
// OkHttp. The server's `add_page` accepts an image with no text, but
// finalization fails when no image-capable analyzer is configured, and the
// analyzer this repository runs against reports
// `placeholder-1.0.0, offline: true`. Recognizing on the glasses keeps the
// documented contract -- upload the JPEG *and* the text -- and keeps the
// system working with no cloud key at all.
android {
    namespace = "dev.rokid.docscanglass.doc"
    compileSdk = 36
    enableKotlin = false

    // GlassDocApi reports its own version to the server as `client_version`,
    // the same field the phone relay sends. AGP 8 stops generating BuildConfig
    // unless it is asked; `:app` asks the same way.
    buildFeatures {
        buildConfig = true
    }

    defaultConfig {
        applicationId = "dev.rokid.docscanglass.doc"
        // YodaOS-Sprite reports API 32. 28 matches the other glasses modules.
        minSdk = 28
        targetSdk = 36
        // 2 is the first build shaped by hardware. 0.1.0 uploaded three pages
        // upside down at mean luminance 16-24 out of 255 and created two
        // documents from two taps. This one rotates by the measured 180
        // degrees, biases exposure +2 EV, guards the document request rather
        // than its response, and shows the operator the still before sending
        // it, because there is no viewfinder that does not hold the privacy
        // indicator lit.
        // 3 adds the aiming guide. A live viewfinder would hold the privacy
        // indicator lit for the whole session; corner brackets drawn on the
        // HUD cost no camera time. The visible fraction is calibrated at run
        // time with `--ef guide`, because the 480x640 display and the
        // 4032x3024 sensor do not share a field of view.
        // 4 undoes the exposure bias 3 introduced. On hardware it stopped the
        // capture completing at all -- four consecutive 15 s timeouts, no
        // image -- where the untouched still template had returned seven
        // frames in 785-1380 ms. It also keeps the last still on the HUD
        // through a failure, because "FAILED" with a blank screen tells the
        // operator nothing about what to change.
        // 5 replaces the home-grown border-luminance framing check with the
        // relay's PageFraming, now shared through `:pagequality`. The operator
        // judged the relay's better on hardware, and it is: it works from the
        // bounding boxes of recognized lines, so it names the side that is cut.
        // 5 also hands the recognizer the measured 180-degree rotation, which
        // is why the first run read upside-down Japanese as noise.
        versionCode = 5
        versionName = "0.5.0"
    }

    // Same reasoning as `:glassapp`: a vendor installer that reads JAR
    // signatures rejects a v2-only APK, and AGP disables v1 on its own above
    // minSdk 24.
    signingConfigs {
        getByName("debug") {
            enableV1Signing = true
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    testOptions {
        unitTests.isIncludeAndroidResources = false
    }
}

dependencies {
    // The gesture contract `:glassapp` validated on hardware, not a copy of it.
    implementation(project(":glassinput"))
    // PageFraming/ShotScore, the framing check the relay already proved. The
    // glasses app used to compute its own from border luminance; the operator
    // reported the relay's was better on hardware, and it is.
    implementation(project(":pagequality"))
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.google.mlkit:text-recognition-japanese:16.0.1")
    testImplementation("junit:junit:4.13.2")
}
