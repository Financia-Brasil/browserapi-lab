plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}
android {
    namespace = "com.ifpa.iassistente"
    buildFeatures { buildConfig = true }
    compileSdk = 35
    defaultConfig {
        applicationId = "com.ifpa.iassistente"
        minSdk = 26
        targetSdk = 35
        versionCode = 3
        versionName = "0.2.0-beta"
    }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget = "17" }
    buildTypes { getByName("debug") { applicationIdSuffix = ".beta" } }
}
dependencies {
    implementation("androidx.webkit:webkit:1.12.1")
    testImplementation("junit:junit:4.13.2")
}
