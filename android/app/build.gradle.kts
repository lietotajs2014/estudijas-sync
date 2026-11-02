import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// Paraksta atslēga: no vides mainīgajiem (GitHub Actions secrets) vai android/keystore.properties
val ksFile = rootProject.file("keystore.properties")
val ks = Properties().apply { if (ksFile.exists()) ksFile.inputStream().use { load(it) } }
fun sign(key: String): String? = System.getenv(key) ?: ks.getProperty(key)

android {
    namespace = "lv.rtu.estudijas"
    compileSdk = 35

    defaultConfig {
        applicationId = "lv.rtu.estudijas.sync"
        minSdk = 26
        targetSdk = 35
        versionCode = (System.getenv("GITHUB_RUN_NUMBER") ?: "1").toInt()
        versionName = "1.0." + (System.getenv("GITHUB_RUN_NUMBER") ?: "0")
    }

    signingConfigs {
        create("release") {
            val path = sign("ANDROID_KEYSTORE_PATH")
            if (path != null && file(path).exists()) {
                storeFile = file(path)
                storePassword = sign("ANDROID_KEYSTORE_PASSWORD")
                keyAlias = sign("ANDROID_KEY_ALIAS") ?: "estudijas"
                keyPassword = sign("ANDROID_KEY_PASSWORD") ?: storePassword
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            val rel = signingConfigs.getByName("release")
            signingConfig = if (rel.storeFile != null) rel else signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    lint { abortOnError = false; checkReleaseBuilds = false }
}
