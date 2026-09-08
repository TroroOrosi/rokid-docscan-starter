plugins {
    id("java-library")
}

// The gesture contract, shared by every glasses-side app.
//
// Pure Java on purpose. Every class here was already free of android imports,
// so keeping it off the Android plugin means the normalizer's tests run in
// milliseconds and a failure can only be a logic failure. `:glassapp` proves
// the contract against hardware; `:glassdoc` relies on it in production.
java {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
}

dependencies {
    testImplementation("junit:junit:4.13.2")
}
