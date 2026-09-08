plugins {
    id("java-library")
}

// Page framing and shot scoring, shared by the phone relay and the glasses app.
//
// Extracted rather than reimplemented. `:glassdoc` 0.3.0 grew its own framing
// heuristic from border luminance, and the operator's verdict on hardware was
// that the relay's check was better -- which it is: PageFraming works from the
// bounding boxes of recognized text lines, so it knows which side of the page
// is cut, not merely that the border is dark.
//
// The package stays `dev.rokid.docscanrelay` on purpose. Both classes are
// self-contained -- java.util and nothing else -- so moving them out of `:app`
// this way needs no edit anywhere in `:app` at all.
java {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
}

dependencies {
    testImplementation("junit:junit:4.13.2")
}
