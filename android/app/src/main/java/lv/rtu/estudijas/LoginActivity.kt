package lv.rtu.estudijas

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Intent
import android.graphics.Bitmap
import android.os.Bundle
import android.util.Base64
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.ViewGroup.LayoutParams.MATCH_PARENT
import android.view.ViewGroup.LayoutParams.WRAP_CONTENT
import android.webkit.CookieManager
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import org.json.JSONObject
import java.security.MessageDigest
import java.security.SecureRandom

/**
 * Pieteikšanās estudijās ar RTU (Microsoft) kontu tāpat kā oficiālajā Moodle lietotnē:
 * atver admin/tool/mobile/launch.php, lietotājs ielogojas (arī MFA), un Moodle novirza uz
 * moodlemobile://token=BASE64(paraksts:::tokens:::privātais_tokens). Parole netiek redzēta.
 */
class LoginActivity : Activity() {
    private lateinit var web: WebView
    private lateinit var progress: ProgressBar
    private val passport = (100_000_000 + SecureRandom().nextInt(899_999_999)).toString()
    private var done = false
    private var email = ""

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        email = intent.getStringExtra("email") ?: ""
        val dp = { v: Int -> TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v.toFloat(), resources.displayMetrics).toInt() }

        val bar = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(16), dp(8), dp(8), dp(8))
            addView(TextView(this@LoginActivity).apply {
                text = "Pieslēgšanās estudijām"
                setTextSize(TypedValue.COMPLEX_UNIT_SP, 18f)
            }, LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f))
            addView(Button(this@LoginActivity).apply {
                text = "Atcelt"
                setOnClickListener { finishWith(null, null, null) }
            })
        }
        progress = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply { max = 100 }
        web = WebView(this)
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            addView(bar, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT))
            addView(progress, LinearLayout.LayoutParams(MATCH_PARENT, dp(4)))
            addView(web, LinearLayout.LayoutParams(MATCH_PARENT, 0, 1f))
        }
        root.padForSystemBars()
        setContentView(root)

        with(web.settings) {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = false
            allowContentAccess = false
        }
        // Moodle sesiju izdzēš, lai pieteikšanās būtu "svaiga" (tad Moodle iedod arī privāto tokenu).
        // Microsoft sīkdatnes paliek — bieži nav jāievada viss no jauna.
        val cm = CookieManager.getInstance()
        cm.setAcceptCookie(true)
        cm.setAcceptThirdPartyCookies(web, true)
        for (name in listOf("MoodleSession", "MoodleSessionTest", "MOODLEID1_")) {
            cm.setCookie("https://$SITE_HOST", "$name=; Max-Age=0; Path=/")
        }
        cm.flush()

        web.webChromeClient = object : WebChromeClient() {
            override fun onProgressChanged(view: WebView, newProgress: Int) {
                progress.progress = newProgress
                progress.visibility = if (newProgress >= 100) View.INVISIBLE else View.VISIBLE
            }
        }
        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean =
                intercept(request.url.toString())

            override fun onPageStarted(view: WebView, url: String, favicon: Bitmap?) {
                if (intercept(url)) view.stopLoading()
            }

            override fun onPageFinished(view: WebView, url: String) {
                if (done) return
                // dažkārt žetons ir lapas saitē, nevis pāradresācijā
                view.evaluateJavascript(
                    "(function(){var m=document.documentElement.innerHTML.match(/[a-z][a-z0-9+.-]*:\\/\\/token=[A-Za-z0-9+\\/=_-]+/);return m?m[0]:''})()"
                ) { r -> val s = try { JSONObject("{\"v\":$r}").getString("v") } catch (e: Exception) { "" }; if (s.isNotEmpty()) intercept(s) }
                if (email.isNotBlank() && url.contains("login.microsoftonline.com")) {
                    val e = JSONObject.quote(email)
                    view.evaluateJavascript(
                        "(function(){var i=document.querySelector('input[name=loginfmt]');" +
                            "if(i&&!i.value){i.value=$e;i.dispatchEvent(new Event('input',{bubbles:true}));}})()", null
                    )
                }
            }

            override fun onReceivedError(view: WebView, request: WebResourceRequest, error: WebResourceError) {
                if (request.isForMainFrame) intercept(request.url.toString())
            }
        }
        web.loadUrl(
            "https://$SITE_HOST/admin/tool/mobile/launch.php?service=moodle_mobile_app" +
                "&passport=$passport&urlscheme=moodlemobile"
        )
    }

    /** true — URL apstrādāts (žetons vai ne-http shēma). */
    private fun intercept(url: String): Boolean {
        if (url.startsWith("http://") || url.startsWith("https://") || url.startsWith("about:")) return false
        if (done) return true
        val m = Regex("token=([A-Za-z0-9+/=_-]+)").find(url) ?: return true
        try {
            var b64 = m.groupValues[1]
            b64 += "=".repeat((4 - b64.length % 4) % 4)
            val flags = if (b64.contains('-') || b64.contains('_')) Base64.URL_SAFE else Base64.DEFAULT
            val parts = String(Base64.decode(b64, flags), Charsets.UTF_8).split(":::")
            if (parts.size < 2 || parts[1].isBlank()) throw IllegalStateException("Nesaprotams žetons")
            val expected = md5("https://$SITE_HOST$passport")
            if (parts[0] != expected) android.util.Log.i("estudijas", "Žetona paraksts nesakrīt (nav kritiski)")
            finishWith(parts[1], parts.getOrNull(2) ?: "", null)
        } catch (e: Exception) {
            finishWith(null, null, "Neizdevās nolasīt piekļuves žetonu: ${e.message}")
        }
        return true
    }

    private fun md5(s: String) = MessageDigest.getInstance("MD5").digest(s.toByteArray()).joinToString("") { "%02x".format(it) }

    private fun finishWith(token: String?, priv: String?, error: String?) {
        if (done) return
        done = true
        val data = Intent()
        token?.let { data.putExtra("token", it) }
        priv?.let { data.putExtra("private", it) }
        error?.let { data.putExtra("error", it) }
        setResult(if (token != null) RESULT_OK else RESULT_CANCELED, data)
        finish()
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (web.canGoBack()) web.goBack() else finishWith(null, null, null)
    }

    override fun onDestroy() {
        web.destroy()
        super.onDestroy()
    }
}
