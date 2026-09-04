plugins {
    id("com.android.application")
}

// A throwaway capability spike that runs on the glasses, not on the phone. It
// settles four questions in one install: the real display metrics, whether the
// camera opens at all, whether the glasses' own Wi-Fi reaches the FastAPI
// server, and whether KEYCODE_BACK can be consumed so a double tap stops
// ending the session.
//
// It is a separate module on purpose. :glassapp's verified record leans on it
// requesting no Android permissions and containing no camera, network, or
// upload operation; adding CAMERA and INTERNET there would destroy that
// property before the owning capture module is even specified.
android {
    namespace = "dev.rokid.docscanglass.probe"
    compileSdk = 36
    enableKotlin = false

    defaultConfig {
        applicationId = "dev.rokid.docscanglass.probe"
        // YodaOS-Sprite is Android 12 (API 32 on the measured build). 28 matches
        // :glassapp and the working reference implementation.
        minSdk = 28
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
    }

    // Kept at parity with :glassapp. Whether the glasses installer needs a v1
    // (JAR) signature was never isolated as a variable, and direct adb install
    // does not care either way, so this only avoids introducing a difference.
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
    // Annotations only: no native code and no runtime behaviour, so a negative
    // probe result still means "the platform refused", not "a library did".
    // Present because lint reports MissingPermission as an error and the guard
    // for openCamera is a plain checkSelfPermission call.
    compileOnly("androidx.annotation:annotation:1.9.1")

    testImplementation("junit:junit:4.13.2")
}
