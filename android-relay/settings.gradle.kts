pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
        maven { url = uri("https://maven.rokid.com/repository/maven-public/") }
    }
}

rootProject.name = "RokidDocScanRelay"
include(":app")

// The capture pipeline `:app` and `:glassdoc` share. Extracted so the glasses
// run the relay's tested controller, OCR, upload and review instead of a
// second implementation of the same thing.
include(":relaycore")
// Runs on the glasses, not the phone. Kept out of :app's dependencies on
// purpose: its APK is pushed to the phone and uploaded at run time, so a
// throwaway probe never ships inside a relay build.
include(":glassapp")
// A throwaway capability spike, also on the glasses. Separate from :glassapp so
// that adding CAMERA and INTERNET here cannot weaken :glassapp's verified
// no-permission, no-side-effect record.
include(":glassprobe")

// The gesture contract, shared by the glasses-side apps. A plain java-library:
// every class in it was already free of android imports, so the tests run
// without an Android runtime and a failure can only be a logic failure.
include(":glassinput")

// The glasses-side document scanner. This is the product of the 2026-09-04
// spike: the glasses own capture, OCR and the server connection, and the phone
// is not in the data path.
include(":glassdoc")

// Page framing and shot scoring, shared by `:app` and `:glassdoc`. Extracted
// from the relay rather than reimplemented on the glasses: the relay's check
// works from recognized-text bounding boxes and knows which side is cut.
include(":pagequality")

