package lv.rtu.estudijas

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Intent
import android.graphics.Bitmap
import android.net.Uri
import android.os.Bundle
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

/**
 * Pieteikšanās estudijās ar RTU (Microsoft) kontu tāpat kā oficiālajā Moodle lietotnē:
 * atver admin/tool/mobile/launch.php, lietotājs ielogojas (arī MFA), un Moodle novirza uz
 * moodlemobile://token=BASE64(paraksts:::tokens:::privātais_tokens). Parole netiek redzēta.
 */
class LoginActivity : Activity() {
    private lateinit var web: WebView
    private lateinit var progress: ProgressBar
    private val launch = launchUrl()
    private var relaunches = 0
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
        web.importantForAutofill = View.IMPORTANT_FOR_AUTOFILL_YES
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
                // Pēc Microsoft pieteikšanās estudijas bieži atver sākumlapu, nevis atgriežas pie launch.php —
                // tad launch.php atver vēlreiz (sesija jau ir, tāpēc tas uzreiz atdod žetonu).
                val u = Uri.parse(url)
                val path = u.path ?: ""
                if (u.host == SITE_HOST && !path.startsWith("/login") && !path.startsWith("/auth/") &&
                    path != LAUNCH_PATH && relaunches < 2
                ) {
                    relaunches++
                    view.loadUrl(launch)
                    return
                }
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
        web.loadUrl(launch)
    }

    /** true — URL apstrādāts (žetons vai ne-http shēma). */
    private fun intercept(url: String): Boolean {
        if (url.startsWith("http://") || url.startsWith("https://") || url.startsWith("about:")) return false
        if (done) return true
        try {
            val t = decodeLaunchToken(url) ?: return true
            finishWith(t.first, t.second, null)
        } catch (e: Exception) {
            finishWith(null, null, "Neizdevās nolasīt piekļuves žetonu: ${e.message}")
        }
        return true
    }

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
