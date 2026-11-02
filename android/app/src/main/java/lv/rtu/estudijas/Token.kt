package lv.rtu.estudijas

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.util.Base64
import org.json.JSONObject
import java.io.File
import java.security.SecureRandom

const val LAUNCH_PATH = "/admin/tool/mobile/launch.php"

fun launchUrl(): String {
    val passport = 100_000_000 + SecureRandom().nextInt(899_999_999)
    return "https://$SITE_HOST$LAUNCH_PATH?service=moodle_mobile_app&passport=$passport&urlscheme=moodlemobile"
}

/** moodlemobile://token=BASE64(paraksts:::tokens[:::privātais]) → (tokens, privātais). null — nav žetona. */
fun decodeLaunchToken(url: String): Pair<String, String>? {
    val m = Regex("token=([A-Za-z0-9+/=_-]+)").find(url) ?: return null
    var b64 = m.groupValues[1]
    b64 += "=".repeat((4 - b64.length % 4) % 4)
    val flags = if (b64.contains('-') || b64.contains('_')) Base64.URL_SAFE else Base64.DEFAULT
    val parts = String(Base64.decode(b64, flags), Charsets.UTF_8).split(":::")
    if (parts.size < 2 || parts[1].isBlank()) throw IllegalStateException("Nesaprotams žetons")
    return parts[1] to (parts.getOrNull(2) ?: "")
}

/** Tā pati glabātuve, ko lieto saskarne (Native.load/save). */
object Store {
    private fun dir(ctx: Context) = File(ctx.filesDir, "store").apply { mkdirs() }
    fun file(ctx: Context, key: String) = File(dir(ctx), key.replace(Regex("[^A-Za-z0-9_-]"), "_") + ".json")
    fun load(ctx: Context, key: String): String? = file(ctx, key).takeIf { it.exists() }?.readText()
    fun save(ctx: Context, key: String, value: String) {
        val f = file(ctx, key)
        if (value.isEmpty()) { f.delete(); return }
        val tmp = File(f.path + ".tmp")
        tmp.writeText(value)
        tmp.renameTo(f)
    }
    fun saveAuth(ctx: Context, token: String, priv: String) =
        save(ctx, "auth", JSONObject().put("token", token).put("privatetoken", priv).toString())
}

/** Atver pieteikšanos pārlūkā (Chrome Custom Tab, ja ir) — tur strādā saglabātās paroles un esošā Microsoft sesija. */
fun openBrowserLogin(activity: Activity): Boolean {
    val i = Intent(Intent.ACTION_VIEW, Uri.parse(launchUrl()))
    // Custom Tab bez AndroidX bibliotēkas: pietiek ar šiem papildu laukiem
    i.putExtras(Bundle().apply { putBinder("android.support.customtabs.extra.SESSION", null) })
    i.putExtra("android.support.customtabs.extra.TOOLBAR_COLOR", Color.parseColor("#1B2B3A"))
    i.putExtra("androidx.browser.customtabs.extra.SHARE_STATE", 2)
    return try {
        activity.startActivity(i); true
    } catch (e: ActivityNotFoundException) {
        false
    }
}

/**
 * Pārlūks pēc pieteikšanās atver moodlemobile://token=… — šī aktivitāte to saņem,
 * saglabā žetonu un atgriežas lietotnē.
 */
class TokenActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val url = intent?.dataString ?: ""
        val back = Intent(this, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)
        try {
            val t = decodeLaunchToken(url) ?: throw IllegalStateException("Atbildē nav žetona")
            Store.saveAuth(this, t.first, t.second)
            back.putExtra("token", t.first).putExtra("private", t.second)
        } catch (e: Exception) {
            back.putExtra("error", "Neizdevās nolasīt piekļuves žetonu: ${e.message}")
        }
        startActivity(back)
        finish()
    }
}
