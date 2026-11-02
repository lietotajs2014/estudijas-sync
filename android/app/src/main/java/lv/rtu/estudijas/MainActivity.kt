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

class MainActivity : Activity() {
    private lateinit var web: WebView
    private val pool = Executors.newFixedThreadPool(6)
    private var resumedOnce = false
    private var userAgent = ""

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
        userAgent = web.settings.userAgentString
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

    override fun onPause() {
        super.onPause()
        CookieManager.getInstance().flush()
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
        val ok = resultCode == RESULT_OK
        val err = data?.getStringExtra("error") ?: ""
        js("window.__onLogin && window.__onLogin($ok, ${q(err)})")
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
        /**
         * HTTP pieprasījums uz estudijas.rtu.lv (tikai turp) ar lietotnē ielogotās sesijas sīkdatnēm.
         * Pāradresācijām neseko (JS to dara pats). Rezultāts — window.__nativeResult(id, status, text, location).
         */
        @JavascriptInterface
        fun request(id: String, method: String, url: String, body: String, ctype: String) {
            pool.execute {
                var status = 0
                var text: String
                var location = ""
                try {
                    val u = URL(url)
                    if (u.protocol != "https" || u.host != SITE_HOST) throw SecurityException("Neatļauta adrese")
                    val cm = CookieManager.getInstance()
                    val c = u.openConnection() as HttpURLConnection
                    c.instanceFollowRedirects = false
                    c.requestMethod = if (method == "POST") "POST" else "GET"
                    c.connectTimeout = 20_000
                    c.readTimeout = 90_000
                    c.setRequestProperty("User-Agent", userAgent)
                    cm.getCookie(url)?.let { c.setRequestProperty("Cookie", it) }
                    if (method == "POST") {
                        c.doOutput = true
                        c.setRequestProperty("Content-Type", ctype.ifEmpty { "application/x-www-form-urlencoded" })
                        c.setRequestProperty("X-Requested-With", "XMLHttpRequest")
                        c.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
                    }
                    status = c.responseCode
                    for ((k, v) in c.headerFields) if (k != null && k.equals("Set-Cookie", true)) v.forEach { cm.setCookie(url, it) }
                    location = c.getHeaderField("Location") ?: ""
                    val stream = if (status >= 400) c.errorStream else c.inputStream
                    text = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() } ?: ""
                    c.disconnect()
                } catch (e: Exception) {
                    status = 0
                    text = e.message ?: e.javaClass.simpleName
                }
                js("window.__nativeResult(${q(id)}, $status, ${q(text)}, ${q(location)})")
            }
        }

        /**
         * Pieslēdz web lapu (piem. https://estudijas.lodelo.de): nosūta e-studiju un Microsoft pieteikšanās
         * sīkdatnes uz <server>/api/pair kopā ar 6 ciparu kodu no lapas. Parole netiek sūtīta (lietotnei tās nav).
         * Rezultāts — window.__pairResult(id, ok, message).
         */
        @JavascriptInterface
        fun pairWeb(id: String, server: String, code: String) {
            pool.execute {
                var ok = false
                var msg: String
                try {
                    val base = URL(server.trimEnd('/'))
                    if (base.protocol != "https") throw SecurityException("Servera adresei jāsākas ar https://")
                    val cm = CookieManager.getInstance()
                    val cookies = org.json.JSONArray()
                    for ((host, domain) in listOf(
                        "https://$SITE_HOST/" to SITE_HOST,
                        "https://login.microsoftonline.com/" to "login.microsoftonline.com",
                    )) {
                        cm.getCookie(host)?.split(";")?.forEach { part ->
                            val i = part.indexOf('=')
                            if (i > 0) cookies.put(JSONObject()
                                .put("name", part.substring(0, i).trim())
                                .put("value", part.substring(i + 1).trim())
                                .put("domain", domain).put("path", "/"))
                        }
                    }
                    val body = JSONObject().put("code", code).put("source", "android").put("cookies", cookies).toString()
                    val c = URL(base, "/api/pair").openConnection() as HttpURLConnection
                    c.requestMethod = "POST"
                    c.connectTimeout = 20_000
                    c.readTimeout = 60_000
                    c.doOutput = true
                    c.setRequestProperty("Content-Type", "application/json")
                    c.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
                    val status = c.responseCode
                    val text = (if (status >= 400) c.errorStream else c.inputStream)?.bufferedReader()?.use { it.readText() } ?: ""
                    c.disconnect()
                    val j = try { JSONObject(text) } catch (e: Exception) { JSONObject() }
                    ok = j.optBoolean("ok", false)
                    msg = if (ok) j.optString("fullname").ifEmpty { j.optString("account") }
                          else j.optString("error").ifEmpty { "Serveris atbildēja ar kļūdu (HTTP $status)" }
                } catch (e: Exception) {
                    msg = e.message ?: e.javaClass.simpleName
                }
                js("window.__pairResult && window.__pairResult(${q(id)}, $ok, ${q(msg)})")
            }
        }

        @JavascriptInterface
        fun load(key: String): String? = Store.load(this@MainActivity, key)

        @JavascriptInterface
        fun save(key: String, value: String) = Store.save(this@MainActivity, key, value)

        @JavascriptInterface
        fun openUrl(url: String) = runOnUiThread { openExternal(url) }

        /** Pieteikšanās lietotnes logā (sesijas sīkdatnes vajag lietotnē, tāpēc ne ārējā pārlūkā). */
        @JavascriptInterface
        fun login(email: String) = runOnUiThread {
            @Suppress("DEPRECATION")
            startActivityForResult(Intent(this@MainActivity, LoginActivity::class.java).putExtra("email", email), REQ_LOGIN)
        }

        @JavascriptInterface
        fun clearCookies() = runOnUiThread { CookieManager.getInstance().removeAllCookies(null); CookieManager.getInstance().flush() }

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
