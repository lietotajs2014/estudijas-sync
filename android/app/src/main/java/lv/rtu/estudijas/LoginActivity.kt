package lv.rtu.estudijas

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.ViewGroup.LayoutParams.MATCH_PARENT
import android.view.ViewGroup.LayoutParams.WRAP_CONTENT
import android.webkit.CookieManager
import android.webkit.WebChromeClient
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import org.json.JSONObject

/**
 * Pieteikšanās estudijās ar RTU (Microsoft) kontu lietotnes logā.
 * RTU estudijās mobilās lietotnes API ir izslēgta, tāpēc lietotne izmanto parastu estudiju sesiju:
 * kad pēc pieteikšanās atveras estudiju lapa, sesijas sīkdatnes paliek lietotnē un logs aizveras.
 * Microsoft "Palikt pierakstītam?" tiek apstiprināts automātiski, lai nākamreiz nav jāraksta parole.
 */
class LoginActivity : Activity() {
    private lateinit var web: WebView
    private lateinit var progress: ProgressBar
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
                setOnClickListener { finishWith(false) }
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
        val cm = CookieManager.getInstance()
        cm.setAcceptCookie(true)
        cm.setAcceptThirdPartyCookies(web, true)

        web.webChromeClient = object : WebChromeClient() {
            override fun onProgressChanged(view: WebView, newProgress: Int) {
                progress.progress = newProgress
                progress.visibility = if (newProgress >= 100) View.INVISIBLE else View.VISIBLE
            }
        }
        web.webViewClient = object : WebViewClient() {
            override fun onPageFinished(view: WebView, url: String) {
                if (done) return
                val u = Uri.parse(url)
                val path = u.path ?: ""
                if (u.host == SITE_HOST && !path.startsWith("/login") && !path.startsWith("/auth/")) {
                    // estudiju lapa ar sesskey → pieteicies
                    view.evaluateJavascript("(window.M && M.cfg && M.cfg.sesskey) || ''") { r ->
                        val sk = try { JSONObject("{\"v\":$r}").getString("v") } catch (e: Exception) { "" }
                        if (sk.isNotEmpty()) {
                            CookieManager.getInstance().flush()
                            finishWith(true)
                        }
                    }
                } else if (u.host?.contains("microsoftonline") == true) {
                    val e = JSONObject.quote(email)
                    view.evaluateJavascript(
                        "(function(){" +
                            // "Palikt pierakstītam?" → Jā
                            "if(document.querySelector('#KmsiCheckboxField,#KmsiDescription')){var b=document.querySelector('#idSIButton9');if(b)b.click();return;}" +
                            "var i=document.querySelector('input[name=loginfmt]');var e=$e;" +
                            "if(e&&i&&!i.value){i.value=e;i.dispatchEvent(new Event('input',{bubbles:true}));}" +
                            "})()", null
                    )
                }
            }
        }
        web.loadUrl("https://$SITE_HOST/my/")
    }

    private fun finishWith(ok: Boolean) {
        if (done) return
        done = true
        setResult(if (ok) RESULT_OK else RESULT_CANCELED, Intent())
        finish()
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (web.canGoBack()) web.goBack() else finishWith(false)
    }

    override fun onDestroy() {
        web.destroy()
        super.onDestroy()
    }
}
