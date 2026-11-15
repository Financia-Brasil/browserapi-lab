package com.ifpa.iassistente

import android.annotation.SuppressLint
import android.app.Activity
import android.app.AlertDialog
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.inputmethod.InputMethodManager
import android.webkit.*
import android.widget.*
import androidx.webkit.WebViewAssetLoader
import org.json.JSONArray
import org.json.JSONObject
import java.util.Locale

class MainActivity : Activity() {
    private val prefs by lazy { getSharedPreferences("farol", MODE_PRIVATE) }
    private val handler = Handler(Looper.getMainLooper())
    private lateinit var root: LinearLayout
    private var web: WebView? = null
    private var tts: TextToSpeech? = null
    private var voiceReady = false
    private var foreground = false
    private var paused = false
    private var screen = "home"
    private var lastAdvice = Advice("Aguarde a página carregar.")
    private var lastEnvelope = """{"version":1,"nodes":[],"errors":[]}"""
    private var message: TextView? = null
    private var stateLabel: TextView? = null
    private var address: EditText? = null
    private var speechId = 0
    private var pageGeneration = 0
    private var completedThisVisit = false
    private var captureFailed = false
    private var failedUrl: String? = null
    private val navy = Color.rgb(4,24,63)
    private val blue = Color.rgb(19,81,180)
    private val yellow = Color.rgb(255,205,7)
    private val ink = Color.rgb(51,51,51)
    private val surfaceColor = Color.rgb(240,243,247)
    private val practiceUrl = "https://appassets.androidplatform.net/assets/practice.html"
    private val font by lazy { try { Typeface.createFromAsset(assets,"fonts/AtkinsonHyperlegible-Regular.ttf") } catch (_: Exception) { Typeface.DEFAULT } }
    private val captureScript by lazy { assets.open("capture.js").bufferedReader().use { it.readText() } }
    private val ticker = object : Runnable {
        override fun run() {
            if (foreground && web != null && !paused && !captureFailed) capture(false)
            if (foreground && web != null) handler.postDelayed(this, 1000)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.decorView.setBackgroundColor(navy)
        window.decorView.setOnApplyWindowInsetsListener { view, insets ->
            view.setPadding(insets.systemWindowInsetLeft, insets.systemWindowInsetTop,
                insets.systemWindowInsetRight, insets.systemWindowInsetBottom)
            insets.consumeSystemWindowInsets()
        }
        tts = TextToSpeech(this) { status ->
            if (status == TextToSpeech.SUCCESS) {
                val result = tts?.setLanguage(Locale.forLanguageTag("pt-BR"))
                voiceReady = result != TextToSpeech.LANG_MISSING_DATA && result != TextToSpeech.LANG_NOT_SUPPORTED
                tts?.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                    override fun onStart(utteranceId: String?) { runOnUiThread { if (!paused) stateLabel?.text = "O Farol está lendo" } }
                    override fun onDone(utteranceId: String?) { runOnUiThread { if (utteranceId == speechId.toString() && !paused) stateLabel?.text = lastAdvice.state } }
                    @Deprecated("Legacy TTS error callback")
                    override fun onError(utteranceId: String?) { runOnUiThread { stateLabel?.text = "Não foi possível ler. A orientação está em texto." } }
                })
            }
        }
        if (!prefs.getBoolean("consent",false)) showConsent()
        else if (savedInstanceState?.getString("screen") == "browser") browser(savedInstanceState.getString("url") ?: practiceUrl)
        else home()
    }

    private fun dp(value: Int) = (value * resources.displayMetrics.density + .5f).toInt()
    private fun rounded(color: Int, stroke: Int? = null): GradientDrawable = GradientDrawable().apply {
        setColor(color); cornerRadius = dp(8).toFloat()
        if (stroke != null) setStroke(dp(1),stroke)
    }
    private fun label(value: String, size: Float = 18f, color: Int = ink, bold: Boolean = false): TextView =
        TextView(this).apply {
            text = value; textSize = size; setTextColor(color)
            typeface = if (bold) Typeface.create(font,Typeface.BOLD) else font
            setLineSpacing(0f,1.25f)
        }
    private fun stack(): LinearLayout = LinearLayout(this).apply { orientation=LinearLayout.VERTICAL }
    private fun button(value: String, id: Int = View.NO_ID, secondary: Boolean = false, action: () -> Unit): Button =
        Button(this).apply {
            text = value; this.id = id; textSize=18f; isAllCaps=false; typeface=font
            minHeight=dp(56); minimumHeight=dp(56); setPadding(dp(16),dp(8),dp(16),dp(8))
            setTextColor(if (secondary) blue else Color.WHITE)
            background=android.graphics.drawable.StateListDrawable().apply {
                val fill=if(secondary) Color.WHITE else blue
                addState(intArrayOf(android.R.attr.state_focused),rounded(fill,if(secondary) navy else yellow).apply { setStroke(dp(3),if(secondary) navy else yellow) })
                addState(intArrayOf(android.R.attr.state_pressed),rounded(if(secondary) Color.rgb(224,237,255) else navy,if(secondary) blue else null))
                addState(intArrayOf(),rounded(fill,if(secondary) blue else null))
            }
            setOnClickListener { action() }
            layoutParams=LinearLayout.LayoutParams(-1,-2).apply { topMargin=dp(8); bottomMargin=dp(8) }
        }
    private fun addText(parent: LinearLayout, value: String, size: Float = 18f, bold: Boolean = false) {
        parent.addView(label(value,size,bold=bold),LinearLayout.LayoutParams(-1,-2).apply { bottomMargin=dp(16) })
    }
    private fun leaveBrowser() {
        handler.removeCallbacks(ticker); tts?.stop(); pageGeneration++; paused=false
        web?.let { old -> (old.parent as? ViewGroup)?.removeView(old); old.stopLoading(); old.destroy() }
        web=null; message=null; stateLabel=null; address=null
    }
    private fun base(title: String, canGoHome: Boolean = true): LinearLayout {
        leaveBrowser()
        root=stack().apply { setBackgroundColor(surfaceColor) }
        val bar=LinearLayout(this).apply { gravity=Gravity.CENTER_VERTICAL; setPadding(dp(16),dp(8),dp(16),dp(8)); setBackgroundColor(navy) }
        bar.addView(label("●",24f,yellow),LinearLayout.LayoutParams(dp(32),-2))
        bar.addView(label("Farol",24f,Color.WHITE,true),LinearLayout.LayoutParams(0,-2,1f))
        if (canGoHome) bar.addView(button("Início",R.id.home_button,true) { home() },LinearLayout.LayoutParams(-2,dp(56)))
        root.addView(bar)
        val scroll=ScrollView(this).apply { isFillViewport=true }
        val body=stack().apply { setPadding(dp(24),dp(24),dp(24),dp(24)) }
        scroll.addView(body)
        root.addView(scroll,LinearLayout.LayoutParams(-1,0,1f))
        setContentView(root)
        addText(body,title,28f,true)
        return body
    }
    private fun showConsent() {
        screen="consent"
        val body=base("Você no comando",false)
        addText(body,"O Farol explica a página, marca um campo e pode ler a orientação. Você toca, preenche e decide.")
        addText(body,"Esta versão beta usa um guia básico no aparelho. Não há IA em nuvem nem uso do microfone.")
        addText(body,"Ao navegar em um site real, o próprio site recebe os dados que você enviar para ele.")
        addText(body,"O Farol não envia a captura para nenhum servidor. A captura do guia exclui os valores dos campos.")
        body.addView(button("Ver exemplo da captura",secondary=true) {
            showInfo("Exemplo sem valores","""{"origin":"https://portal.exemplo","nodes":[{"role":"textbox","label":"CPF","filled":true}]}""")
        })
        body.addView(button("Aceitar e começar",R.id.onboarding_accept) {
            prefs.edit().putBoolean("consent",true).apply(); home()
        })
        body.addView(button("Não aceito",R.id.onboarding_refuse,true) {
            prefs.edit().putBoolean("consent",false).apply()
            val refused=base("Sua escolha foi salva",false)
            addText(refused,"O guia fica desativado sem seu consentimento.")
            refused.addView(button("Rever minha escolha") { showConsent() })
        })
    }
    private fun home() {
        screen="home"
        val body=base("Vamos por partes",false)
        addText(body,"Escolha onde você quer ajuda. O Farol mostra o caminho; cada ação é sua.")
        addText(body,"Beta 0.1 · guia local · sem IA em nuvem",16f)
        body.addView(button("Começar treino offline",R.id.start_practice) { browser(practiceUrl) })
        addText(body,"Pratique com um formulário fictício, sem usar dados pessoais.",16f)
        body.addView(button("Abrir um site",R.id.open_browser,true) { browser("https://www.gov.br/") })
        body.addView(button("Meus fluxos",R.id.open_skills,true) { skills() })
        body.addView(button("Voz e privacidade",R.id.open_settings,true) { settingsPage() })
    }
    private fun showInfo(title: String, text: String) {
        val body=ScrollView(this)
        body.addView(label(text,16f).apply { setPadding(dp(24),dp(16),dp(24),dp(16)); setTextIsSelectable(true) })
        AlertDialog.Builder(this).setTitle(title).setView(body).setPositiveButton("Fechar",null).show()
    }
    private fun speak(text: String) {
        if (!prefs.getBoolean("voice",true) || !voiceReady || paused) return
        tts?.setSpeechRate(prefs.getFloat("speed",1f))
        tts?.setPitch(1f)
        speechId++
        val spoken=text.split(Regex("\\s+")).chunked(14).joinToString(". ") { it.joinToString(" ") }
        tts?.speak(spoken,TextToSpeech.QUEUE_FLUSH,null,speechId.toString())
    }
    private fun settingsPage() {
        screen="settings"
        val body=base("Voz e privacidade")
        val voice=Switch(this).apply {
            id=R.id.settings_voice; text="Ler orientações em voz alta"; textSize=18f; typeface=font
            setPadding(0,dp(16),0,dp(16)); minHeight=dp(56); isChecked=prefs.getBoolean("voice",true)
            setOnCheckedChangeListener { _,checked -> prefs.edit().putBoolean("voice",checked).apply(); if (!checked) tts?.stop() }
        }
        body.addView(voice)
        val speedText=label("Velocidade: "+String.format(Locale.forLanguageTag("pt-BR"),"%.1f",prefs.getFloat("speed",1f))+"×")
        body.addView(speedText)
        body.addView(SeekBar(this).apply {
            id=R.id.settings_speed; max=15; progress=((prefs.getFloat("speed",1f)-.5f)*10).toInt()
            contentDescription="Velocidade da voz, de meio a duas vezes"; minimumHeight=dp(56)
            setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
                override fun onStartTrackingTouch(seekBar: SeekBar?) {}
                override fun onStopTrackingTouch(seekBar: SeekBar?) {}
                override fun onProgressChanged(seekBar: SeekBar?,progress: Int,fromUser: Boolean) {
                    val speed=.5f+progress/10f; prefs.edit().putFloat("speed",speed).apply()
                    speedText.text="Velocidade: "+String.format(Locale.forLanguageTag("pt-BR"),"%.1f",speed)+"×"
                }
            })
        })
        body.addView(button("Ouvir uma orientação",R.id.settings_test) {
            if (voiceReady) speak("Olá! Vamos por partes. Você pode repetir a orientação quando quiser.")
            else showInfo("Voz em português","Não encontrei uma voz pt-BR instalada. Nas configurações do Android, procure Saída de texto para voz e instale uma voz em português.")
        })
        addText(body,"Privacidade",24f,true)
        addText(body,"Guia e fluxos ficam neste aparelho. Sem telemetria, microfone ou API de IA. Os sites abertos têm suas próprias políticas.",16f)
        body.addView(button("Ver última captura",R.id.settings_envelope,true) { showInfo("Captura local, sem envio",lastEnvelope) })
        body.addView(button("Apagar dados e revogar",R.id.settings_delete,true) {
            AlertDialog.Builder(this).setTitle("Apagar os dados do Farol?")
                .setMessage("Apaga seus fluxos, preferências e os dados dos sites abertos pelo Farol. O guia volta à tela de consentimento.")
                .setNegativeButton("Cancelar",null).setPositiveButton("Apagar") { _,_ ->
                    prefs.edit().clear().commit()
                    WebStorage.getInstance().deleteAllData()
                    CookieManager.getInstance().removeAllCookies(null); CookieManager.getInstance().flush()
                    val cleaner=WebView(this); cleaner.clearCache(true); cleaner.clearHistory(); cleaner.destroy()
                    lastEnvelope="""{"version":1,"nodes":[],"errors":[]}"""
                    showConsent()
                }.show()
        })
        addText(body,"Versão 0.1.0-beta · IFPA Bragança\nNavegador WebView para prova de conceito. Portais com CAPTCHA, confirmação facial ou app externo podem exigir continuidade fora deste teste.",16f)
    }

    private fun flowArray(): JSONArray = try { JSONArray(prefs.getString("flows","[]")) } catch (_: Exception) { JSONArray() }
    private fun remember(url: String, completed: Boolean = false) {
        val origin = Privacy.origin(url) ?: return
        val key = if (origin == "https://appassets.androidplatform.net") practiceUrl else origin
        val flows=flowArray()
        var found: JSONObject? = null
        for (i in 0 until flows.length()) if (flows.getJSONObject(i).optString("url")==key) found=flows.getJSONObject(i)
        val flow=found ?: JSONObject().put("url",key).put("uses",0).also { flows.put(it) }
        flow.put("name",if (key==practiceUrl) "Treino de formulário" else Uri.parse(origin).host)
        flow.put("verifiedAt",System.currentTimeMillis())
        if (completed) flow.put("uses",flow.optInt("uses")+1)
        prefs.edit().putString("flows",flows.toString()).apply()
    }
    private fun skills() {
        screen="skills"
        val body=base("Meus fluxos")
        val flows=flowArray()
        if (flows.length()==0) {
            addText(body,"Seu primeiro fluxo pode começar com o treino. Ao concluir, ele aparece aqui.")
            body.addView(button("Começar treino") { browser(practiceUrl) })
        }
        for (i in 0 until flows.length()) {
            val flow=flows.getJSONObject(i)
            addText(body,flow.optString("name"),22f,true)
            addText(body,if (flow.optInt("uses")>0) "Treinos concluídos: "+flow.optInt("uses") else "Portal salvo. Guia básico calculado ao abrir.",16f)
            body.addView(button("Abrir "+flow.optString("name")) { browser(flow.getString("url")) })
            body.addView(button("Apagar este fluxo",secondary=true) {
                val kept=JSONArray()
                for (j in 0 until flows.length()) if (j!=i) kept.put(flows.getJSONObject(j))
                prefs.edit().putString("flows",kept.toString()).apply(); skills()
            })
        }
    }
    @SuppressLint("SetJavaScriptEnabled")
    private fun browser(url: String) {
        if (!prefs.getBoolean("consent",false)) { showConsent(); return }
        leaveBrowser(); screen="browser"; paused=false; captureFailed=false; failedUrl=null; completedThisVisit=false
        root=stack().apply { setBackgroundColor(surfaceColor) }
        val top=LinearLayout(this).apply { setPadding(dp(8),dp(4),dp(8),dp(4)); gravity=Gravity.CENTER_VERTICAL; setBackgroundColor(navy) }
        top.addView(button("Voltar",R.id.browser_back,true) {
            web?.let { if (it.canGoBack()) it.goBack() else home() }
        },LinearLayout.LayoutParams(0,dp(56),1f).apply { marginEnd=dp(8) })
        top.addView(label("Farol",22f,Color.WHITE,true).apply { gravity=Gravity.CENTER },LinearLayout.LayoutParams(0,-2,1f))
        top.addView(button("Início",R.id.home_button,true) { home() },LinearLayout.LayoutParams(0,dp(56),1f).apply { marginStart=dp(8) })
        root.addView(top)
        val urlRow=LinearLayout(this).apply { setPadding(dp(8),dp(4),dp(8),dp(4)); gravity=Gravity.CENTER_VERTICAL }
        address=EditText(this).apply {
            id=R.id.browser_address; hint="Endereço do site"; textSize=16f; typeface=font
            inputType=android.text.InputType.TYPE_CLASS_TEXT or android.text.InputType.TYPE_TEXT_VARIATION_URI
            isSingleLine=true; minHeight=dp(48); setText(url); contentDescription="Endereço do site"
            importantForAutofill=View.IMPORTANT_FOR_AUTOFILL_NO
        }
        urlRow.addView(address,LinearLayout.LayoutParams(0,dp(56),1f))
        urlRow.addView(button("Abrir",R.id.browser_go) { navigate(address?.text.toString()) },LinearLayout.LayoutParams(-2,dp(56)).apply { marginStart=dp(8) })
        urlRow.visibility=if(url==practiceUrl) View.GONE else View.VISIBLE
        root.addView(urlRow)
        val loader=WebViewAssetLoader.Builder().addPathHandler("/assets/",WebViewAssetLoader.AssetsPathHandler(this)).build()
        val view=WebView(this)
        web=view; view.id=R.id.browser_web; view.isSaveEnabled=false
        view.importantForAutofill=View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS
        view.settings.apply {
            javaScriptEnabled=true; domStorageEnabled=true
            allowFileAccess=false; allowContentAccess=false
            mixedContentMode=WebSettings.MIXED_CONTENT_NEVER_ALLOW
            javaScriptCanOpenWindowsAutomatically=false
            setSupportMultipleWindows(false); safeBrowsingEnabled=true
            builtInZoomControls=true; displayZoomControls=false
            textZoom=(resources.configuration.fontScale*100).toInt().coerceIn(100,200)
        }
        CookieManager.getInstance().setAcceptThirdPartyCookies(view,false)
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG)
        view.webChromeClient=object : WebChromeClient() {
            override fun onPermissionRequest(request: PermissionRequest?) { request?.deny() }
        }
        view.webViewClient=object : WebViewClient() {
            override fun shouldInterceptRequest(v: WebView,request: WebResourceRequest): WebResourceResponse? = loader.shouldInterceptRequest(request.url)
            override fun shouldOverrideUrlLoading(v: WebView,request: WebResourceRequest): Boolean {
                if (!request.isForMainFrame) return false
                if (Privacy.origin(request.url.toString())==null) {
                    showInfo("Este endereço não pode ser aberto","Use um endereço HTTPS. Downloads e abertura de outros apps ainda não fazem parte deste beta.")
                    return true
                }
                return false
            }
            override fun onPageStarted(v: WebView,url: String?,favicon: android.graphics.Bitmap?) {
                pageGeneration++; captureFailed=false; failedUrl=null; completedThisVisit=false; tts?.stop()
                message?.text="Aguarde a página carregar."; stateLabel?.text="Carregando"
            }
            override fun onPageFinished(v: WebView,url: String?) {
                address?.setText(if (captureFailed) failedUrl ?: url else url)
                if (!paused && !captureFailed) capture(true)
            }
            override fun onReceivedError(v: WebView,request: WebResourceRequest,error: WebResourceError) {
                if (request.isForMainFrame) {
                    captureFailed=true; failedUrl=request.url.toString(); tts?.stop()
                    lastAdvice=Advice("Não foi possível carregar esta página. Confira sua conexão ou abra o treino offline.",state="Página indisponível")
                    message?.text=lastAdvice.text; stateLabel?.text=lastAdvice.state
                }
            }
            override fun onReceivedHttpError(v: WebView,request: WebResourceRequest,response: WebResourceResponse) {
                if (request.isForMainFrame && response.statusCode>=500) {
                    captureFailed=true; failedUrl=request.url.toString(); tts?.stop()
                    lastAdvice=Advice("O portal está indisponível agora. Tente novamente mais tarde.",state="Portal indisponível")
                    message?.text=lastAdvice.text; stateLabel?.text=lastAdvice.state
                }
            }
            override fun onReceivedSslError(v: WebView,sslHandler: SslErrorHandler,error: android.net.http.SslError) {
                sslHandler.cancel(); captureFailed=true; failedUrl=error.url; tts?.stop()
                lastAdvice=Advice("Não foi possível verificar a segurança deste site. Confira o endereço.",state="Conexão bloqueada")
                message?.text=lastAdvice.text; stateLabel?.text=lastAdvice.state
            }
            override fun onRenderProcessGone(v: WebView,detail: RenderProcessGoneDetail): Boolean {
                home(); showInfo("A página foi fechada","O navegador precisou reiniciar. Você pode abrir o treino novamente."); return true
            }
        }
        root.addView(view,LinearLayout.LayoutParams(-1,0,1f))
        val panel=stack().apply { setPadding(dp(16),dp(8),dp(16),dp(8)); background=rounded(navy) }
        stateLabel=label("Guia local · sem IA em nuvem",16f,yellow,true).apply { id=R.id.guidance_state }
        panel.addView(stateLabel)
        message=label("Aguarde a página carregar.",18f,Color.WHITE).apply {
            id=R.id.guidance_text; accessibilityLiveRegion=View.ACCESSIBILITY_LIVE_REGION_POLITE
        }
        panel.addView(message,LinearLayout.LayoutParams(-1,-2).apply { topMargin=dp(8); bottomMargin=dp(8) })
        fun row(vararg buttons: Button) {
            val r=LinearLayout(this)
            buttons.forEachIndexed { i,b -> r.addView(b,LinearLayout.LayoutParams(0,-2,1f).apply {
                if(i>0) marginStart=dp(8); topMargin=dp(4); bottomMargin=dp(4)
            }) }
            panel.addView(r)
        }
        row(button("Explicar tela",R.id.guidance_explain,true) { capture(true) },
            button("Repetir voz",R.id.guidance_repeat,true) {
                if (voiceReady) speak(lastAdvice.text)
                else showInfo("Voz não disponível","A orientação continua em texto. Instale uma voz pt-BR nas configurações do Android.")
            })
        row(button("Outra explicação",R.id.guidance_rephrase,true) { message?.text=lastAdvice.detail; speak(lastAdvice.detail) },
            button("Pausar guia",R.id.guidance_pause,true) {
                paused=!paused; tts?.stop()
                root.findViewById<Button>(R.id.guidance_pause).text=if(paused) "Retomar guia" else "Pausar guia"
                stateLabel?.text=if(paused) "Guia pausado" else "Guia local"
                if(paused) web?.evaluateJavascript("window.__farol && window.__farol.mark(-1)",null) else capture(true)
            })
        row(button("Salvar fluxo",R.id.save_flow,true) {
            remember(web?.url ?: practiceUrl); Toast.makeText(this,"Fluxo salvo neste aparelho",Toast.LENGTH_SHORT).show()
        })
        val panelScroll=ScrollView(this).apply { addView(panel) }
        val panelHeight=(resources.configuration.screenHeightDp*.34f).toInt().coerceIn(128,264)
        root.addView(panelScroll,LinearLayout.LayoutParams(-1,dp(panelHeight)))
        setContentView(root); navigate(url)
        handler.removeCallbacks(ticker); if (foreground) handler.postDelayed(ticker,1000)
    }
    private fun navigate(raw: String) {
        val url=raw.trim().let { if ("://" in it || it.contains(":")) it else "https://$it" }
        if (Privacy.origin(url)==null) { showInfo("Confira o endereço","Abra um site com HTTPS, por exemplo https://www.gov.br."); return }
        (getSystemService(INPUT_METHOD_SERVICE) as InputMethodManager).hideSoftInputFromWindow(address?.windowToken,0)
        web?.loadUrl(url)
    }
    private fun capture(force: Boolean) {
        if (!prefs.getBoolean("consent",false) || paused) return
        val current=web ?: return
        if (captureFailed) {
            if (force) navigate(failedUrl ?: current.url ?: practiceUrl)
            return
        }
        val generation=pageGeneration
        if(force) current.evaluateJavascript("if(window.__farol)window.__farol.force=true",null)
        current.evaluateJavascript(captureScript) { encoded ->
            if (web!==current || generation!=pageGeneration || paused || !foreground) return@evaluateJavascript
            try {
                if(encoded=="null" || encoded.isNullOrBlank()) return@evaluateJavascript
                val snapshot=JSONObject(encoded)
                lastEnvelope=snapshot.toString(2)
                val nodes=snapshot.getJSONArray("nodes")
                val targets=(0 until nodes.length()).map { i ->
                    val n=nodes.getJSONObject(i)
                    Target(n.getInt("index"),n.getString("role"),Privacy.clean(n.optString("label")),n.optBoolean("filled"),n.optBoolean("sensitive"))
                }
                val error=snapshot.getJSONArray("errors").optString(0).ifBlank { null }
                val complete=snapshot.optBoolean("complete")
                val advice=LocalPlanner.plan(targets,error,complete)
                val changed=advice!=lastAdvice
                lastAdvice=advice
                message?.text=advice.text; stateLabel?.text=advice.state
                current.evaluateJavascript("window.__farol && window.__farol.mark("+ (advice.target ?: -1)+")",null)
                if(changed || force) speak(advice.text)
                if(complete && !completedThisVisit && current.url==practiceUrl) {
                    completedThisVisit=true; remember(practiceUrl,true)
                }
            } catch (_: Exception) {
                stateLabel?.text="Esta página ainda não oferece campos para o guia"
            }
        }
    }
    override fun onSaveInstanceState(outState: Bundle) {
        outState.putString("screen",screen)
        outState.putString("url",failedUrl ?: web?.url)
        super.onSaveInstanceState(outState)
    }
    override fun onResume() {
        super.onResume(); foreground=true; web?.onResume()
        handler.removeCallbacks(ticker); if(web!=null)handler.postDelayed(ticker,500)
    }
    override fun onPause() {
        foreground=false; handler.removeCallbacks(ticker); tts?.stop(); web?.onPause()
        super.onPause()
    }
    @Deprecated("Back navigation on this proof of concept")
    override fun onBackPressed() {
        if(screen=="browser" && web?.canGoBack()==true) web?.goBack()
        else if(screen=="home" || screen=="consent") super.onBackPressed() else home()
    }
    override fun onDestroy() {
        leaveBrowser(); tts?.shutdown(); tts=null
        super.onDestroy()
    }
}
