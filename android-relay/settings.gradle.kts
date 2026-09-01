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
// Runs on the glasses, not the phone. Kept out of :app's dependencies on
// purpose: its APK is pushed to the phone and uploaded at run time, so a
// throwaway probe never ships inside a relay build.
include(":glassapp")
