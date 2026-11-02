package lv.rtu.estudijas

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.CalendarContract
import android.webkit.CookieManager
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.Toast
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors

const val SITE_HOST = "estudijas.rtu.lv"
const val USER_AGENT = "Mozilla/5.0 (Linux; Android) estudijas-sync-android MoodleMobile"

class MainActivity : Activity() {
    private lateinit var web: WebView
    private val pool = Executors.newFixedThreadPool(6)
    private var resumedOnce = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        web = WebView(this)
        web.setBackgroundColor(Color.TRANSPARENT)
        val root = FrameLayout(this)
        root.addView(web, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
        root.padForSystemBars()
        setContentView(root)
        with(web.settings) {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = false      // file:///android_asset joprojām ir pieejams
            allowContentAccess = false
            setSupportMultipleWindows(false)
        }
        web.webChromeClient = WebChromeClient()
        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val url = request.url
                if (url.scheme == "file") return false
                openExternal(url.toString())
                return true
            }
        }
        web.addJavascriptInterface(Bridge(), "Native")
        if (savedInstanceState != null) web.restoreState(savedInstanceState)
        else web.loadUrl("file:///android_asset/web/index.html")
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        deliverLogin(intent)
    }

    /** Žetons no TokenActivity (pieteikšanās pārlūkā). */
    private fun deliverLogin(intent: Intent?) {
        if (intent == null || !(intent.hasExtra("token") || intent.hasExtra("error"))) return
        val token = intent.getStringExtra("token") ?: ""
        val priv = intent.getStringExtra("private") ?: ""
        val err = intent.getStringExtra("error") ?: ""
        intent.removeExtra("token"); intent.removeExtra("error")
        js("window.__onLogin && window.__onLogin(${q(token)}, ${q(priv)}, ${q(err)})")
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        web.saveState(outState)
    }

    override fun onResume() {
        super.onResume()
        if (resumedOnce) web.evaluateJavascript("window.__onResume && window.__onResume()", null)
        resumedOnce = true
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        web.evaluateJavascript("window.__onBack ? window.__onBack() : false") { handled ->
            if (handled != "true") finish()
        }
    }

    override fun onDestroy() {
        pool.shutdownNow()
        web.destroy()
        super.onDestroy()
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        @Suppress("DEPRECATION")
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != REQ_LOGIN) return
        val token = data?.getStringExtra("token") ?: ""
        val priv = data?.getStringExtra("private") ?: ""
        val err = data?.getStringExtra("error") ?: if (token.isEmpty() && resultCode == RESULT_OK) "Pieteikšanās neizdevās" else ""
        js("window.__onLogin(${q(token)}, ${q(priv)}, ${q(err)})")
    }

    private fun js(code: String) = runOnUiThread { web.evaluateJavascript(code, null) }
    private fun q(s: String) = JSONObject.quote(s)

    private fun openExternal(url: String) {
        val uri = Uri.parse(url)
        if (uri.scheme !in setOf("http", "https", "mailto", "tel")) return
        try {
            startActivity(Intent(Intent.ACTION_VIEW, uri).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        } catch (e: ActivityNotFoundException) {
            Toast.makeText(this, "Nav lietotnes, ar ko atvērt šo saiti", Toast.LENGTH_LONG).show()
        }
    }

    inner class Bridge {
        /** HTTP pieprasījums uz estudijas.rtu.lv (tikai turp). Rezultāts — window.__nativeResult(id, status, text). */
        @JavascriptInterface
        fun request(id: String, method: String, url: String, body: String, ctype: String) {
            pool.execute {
                var status = 0
                var text: String
                try {
                    val u = URL(url)
                    if (u.protocol != "https" || u.host != SITE_HOST) throw SecurityException("Neatļauta adrese")
                    val c = u.openConnection() as HttpURLConnection
                    c.requestMethod = if (method == "POST") "POST" else "GET"
                    c.connectTimeout = 20_000
                    c.readTimeout = 90_000
                    c.setRequestProperty("User-Agent", USER_AGENT)
                    c.setRequestProperty("Accept", "application/json")
                    if (method == "POST") {
                        c.doOutput = true
                        c.setRequestProperty("Content-Type", ctype.ifEmpty { "application/x-www-form-urlencoded" })
                        c.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
                    }
                    status = c.responseCode
                    val stream = if (status >= 400) c.errorStream else c.inputStream
                    text = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() } ?: ""
                    c.disconnect()
                } catch (e: Exception) {
                    status = 0
                    text = e.message ?: e.javaClass.simpleName
                }
                js("window.__nativeResult(${q(id)}, $status, ${q(text)})")
            }
        }

        @JavascriptInterface
        fun load(key: String): String? = Store.load(this@MainActivity, key)

        @JavascriptInterface
        fun save(key: String, value: String) = Store.save(this@MainActivity, key, value)

        @JavascriptInterface
        fun openUrl(url: String) = runOnUiThread { openExternal(url) }

        /** mode "browser" — pārlūkā (saglabātās paroles); "app" — lietotnes iekšējā logā. */
        @JavascriptInterface
        fun login(email: String, mode: String) = runOnUiThread {
            if (mode == "browser" && openBrowserLogin(this@MainActivity)) return@runOnUiThread
            @Suppress("DEPRECATION")
            startActivityForResult(Intent(this@MainActivity, LoginActivity::class.java).putExtra("email", email), REQ_LOGIN)
        }

        @JavascriptInterface
        fun clearCookies() = runOnUiThread { CookieManager.getInstance().removeAllCookies(null) }

        @JavascriptInterface
        fun addEvent(title: String, begin: Double, end: Double, description: String, location: String) = runOnUiThread {
            val i = Intent(Intent.ACTION_INSERT).setData(CalendarContract.Events.CONTENT_URI)
                .putExtra(CalendarContract.Events.TITLE, title)
                .putExtra(CalendarContract.EXTRA_EVENT_BEGIN_TIME, begin.toLong())
                .putExtra(CalendarContract.EXTRA_EVENT_END_TIME, end.toLong())
                .putExtra(CalendarContract.Events.DESCRIPTION, description)
                .putExtra(CalendarContract.Events.EVENT_LOCATION, location)
            try {
                startActivity(i)
            } catch (e: ActivityNotFoundException) {
                Toast.makeText(this@MainActivity, "Nav kalendāra lietotnes", Toast.LENGTH_LONG).show()
            }
        }

        @JavascriptInterface
        fun version(): String = try {
            val p = packageManager.getPackageInfo(packageName, 0)
            val code = if (Build.VERSION.SDK_INT >= 28) p.longVersionCode else @Suppress("DEPRECATION") p.versionCode.toLong()
            "${p.versionName} ($code)"
        } catch (e: Exception) { "?" }
    }

    companion object {
        const val REQ_LOGIN = 1
    }
}
