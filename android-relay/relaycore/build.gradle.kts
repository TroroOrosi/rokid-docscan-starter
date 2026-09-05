plugins {
    id("com.android.library")
}

// The capture-to-review pipeline, shared by the phone relay and the glasses
// app.
//
// Everything here was in `:app`, and all of it is device-independent: the
// controller state machine, the bundled Japanese recognizer, the server
// client, the review store and its crash-safe persistence, the HUD layout and
// the gesture vocabulary. CXR-L never appears -- its imports live in exactly
// one file, `RokidGlobalLink`, which stays in `:app` and implements
// `CaptureSurface` from here.
//
// The package stays `dev.rokid.docscanrelay`, the same trick `:pagequality`
// used, so no source file in `:app` needed an edit to find these classes.
// Only the namespace differs, because two modules cannot generate R and
// BuildConfig into the same one.
android {
    namespace = "dev.rokid.docscanrelay.core"
    compileSdk = 36
    enableKotlin = false

    defaultConfig {
        // The relay is minSdk 31 and the glasses report API 32, but the other
        // glasses modules are 28 and this has to load under all of them.
        minSdk = 28
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
    // `api`, not `implementation`: `JapaneseOcr.Callback` hands `PageFraming`
    // to whoever implements it, so the type is part of this module's surface.
    api(project(":pagequality"))
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.google.mlkit:text-recognition-japanese:16.0.1")

    testImplementation("junit:junit:4.13.2")
}
