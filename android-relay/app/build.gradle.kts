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
        versionCode = 9
        versionName = "0.3.4"

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
    implementation("com.rokid.cxr:client-l:1.0.1")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.google.mlkit:text-recognition-japanese:16.0.1")

    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test:runner:1.6.2")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
}
