plugins {
    id("com.android.application")
}

// The glasses-side probe. Deliberately depends on nothing: no androidx, no
// CXR-S, no native libraries. The question it exists to answer is whether an
// ordinary Android app running on the glasses receives operator input at all,
// and every dependency added here is another way for a negative result to mean
// something other than "no input arrived".
android {
    namespace = "dev.rokid.docscanglass"
    compileSdk = 36
    enableKotlin = false

    defaultConfig {
        applicationId = "dev.rokid.docscanglass"
        // YodaOS-Sprite is Android 12 (API 31). 28 matches the working
        // reference implementation and leaves room for older firmware.
        minSdk = 28
        targetSdk = 36
        versionCode = 7
        versionName = "0.1.6"
    }

    // AGP turns v1 (JAR) signing off on its own once minSdk is 24 or above, so
    // this APK shipped with a v2 signature and nothing else, and the glasses
    // answered onInstallAppResult(false) after 43 s. Android 12's own
    // PackageManager accepts v2 alone; a vendor installer that reads JAR
    // signatures does not. v1 is turned back on here as the single variable of
    // that experiment -- v2 and v3 are left exactly as they were.
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
    testImplementation("junit:junit:4.13.2")
}
