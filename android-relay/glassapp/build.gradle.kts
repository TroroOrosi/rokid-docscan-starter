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
        versionCode = 1
        versionName = "0.1.0"
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
