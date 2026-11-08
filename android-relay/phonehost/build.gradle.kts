plugins {
    id("com.android.application")
}

android {
    namespace = "dev.rokid.docscanhost"
    compileSdk = 36
    enableKotlin = false

    defaultConfig {
        applicationId = "dev.rokid.docscanhost"
        minSdk = 31
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
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
    testImplementation("org.robolectric:robolectric:4.14.1")
}
