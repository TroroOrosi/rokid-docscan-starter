plugins {
    id("com.android.application")
}

android {
    namespace = "dev.rokid.docscanrelay"
    compileSdk = 36
    enableKotlin = false
    buildFeatures {
        buildConfig = true
    }

    defaultConfig {
        applicationId = "dev.rokid.docscanrelay"
        minSdk = 31
        targetSdk = 36
        // 4 is skipped: the real-device test phone already carries a
        // versionCode 4 build, and installing a lower code fails with
        // INSTALL_FAILED_VERSION_DOWNGRADE without a data-losing uninstall.
        // 6 carried the echo-ordering fix and the framing verdict, 7 the
        // countdown registration, 8 hands-free burst reading; 9 takes the
        // OS double-tap exit as the retake signal and retries an unreadable
        // burst at once.
        // 10 fixes menu-exit recovery, which skipped itself because the
        // service reports the CustomView as open even on the home screen.
        // 11 stops asking the service at all on a close callback: it answers
        // "still open" for every one of them, so no tap ever reached the relay.
        // 12 narrows that close-derived input to CAPTURE_REVIEW, the one state
        // measured to deliver no AI event, and reports why a command was
        // ignored when the glasses link is down instead of returning silently.
        // 13 corrects the operator guidance: the shutter was documented as a
        // 1.5 s hold, but takePhoto measured 5.2 s to its callback, so moving
        // at 1.5 s blurs the page.
        versionCode = 17
        versionName = "0.3.12"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
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
    implementation("com.rokid.cxr:client-l:1.1.1")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.google.mlkit:text-recognition-japanese:16.0.1")

    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test:runner:1.6.2")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
}
