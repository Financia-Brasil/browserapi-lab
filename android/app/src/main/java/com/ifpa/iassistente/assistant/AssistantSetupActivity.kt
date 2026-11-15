package com.ifpa.iassistente.assistant

import android.Manifest
import android.app.Activity
import android.app.role.RoleManager
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.view.View
import android.widget.*
import com.ifpa.iassistente.R

class AssistantSetupActivity : Activity() {
    private fun dp(n: Int)=(n*resources.displayMetrics.density+.5f).toInt()
    override fun onCreate(state: Bundle?) { super.onCreate(state);render() }
    override fun onResume() { super.onResume();render() }
    private fun render() {
        val scroll=ScrollView(this)
        val box=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL;setPadding(dp(24),dp(24),dp(24),dp(24));setBackgroundColor(Color.rgb(240,243,247)) }
        scroll.addView(box)
        val font=try { Typeface.createFromAsset(assets,"fonts/AtkinsonHyperlegible-Regular.ttf") }catch(_:Exception){Typeface.DEFAULT}
        fun text(value: String,size: Float=18f) { box.addView(TextView(this).apply { text=value;textSize=size;typeface=font;setTextColor(Color.rgb(4,24,63));setPadding(0,0,0,dp(16)) }) }
        fun button(value: String,id: Int,action:()->Unit) { box.addView(Button(this).apply {
            text=value;this.id=id;isAllCaps=false;textSize=18f;typeface=font;minimumHeight=dp(56);setPadding(dp(16),dp(8),dp(16),dp(8));setTextColor(Color.WHITE)
            background=GradientDrawable().apply { setColor(Color.rgb(19,81,180));cornerRadius=dp(8).toFloat() }
            layoutParams=LinearLayout.LayoutParams(-1,-2).apply { topMargin=dp(8);bottomMargin=dp(16) };setOnClickListener{action()}
        }) }
        text("Farol sobre seus aplicativos",28f)
        text("Depois desta preparação, chame o Farol pelo gesto de assistente ou mantendo o botão Início pressionado. O aplicativo atual continua atrás do painel.")
        val held=if(Build.VERSION.SDK_INT>=29)getSystemService(RoleManager::class.java).isRoleHeld(RoleManager.ROLE_ASSISTANT) else FarolVoiceService.active!=null
        text(if(held)"Farol é o assistente escolhido." else "Escolha o Farol como assistente do Android.")
        button("Definir Farol como assistente",R.id.assistant_set_default) {
            FarolSpeech.rememberEngine(this)
            val prefs=getSharedPreferences("farol",MODE_PRIVATE)
            if(!prefs.contains("original_assistant"))prefs.edit()
                .putString("original_assistant",Settings.Secure.getString(contentResolver,"assistant"))
                .putString("original_voice_service",Settings.Secure.getString(contentResolver,"voice_interaction_service")).apply()
            if(Build.VERSION.SDK_INT>=29) {
                val roles=getSystemService(RoleManager::class.java)
                if(roles.isRoleAvailable(RoleManager.ROLE_ASSISTANT))startActivityForResult(roles.createRequestRoleIntent(RoleManager.ROLE_ASSISTANT),51)
                else startActivity(Intent(Settings.ACTION_VOICE_INPUT_SETTINGS))
            }else startActivity(Intent(Settings.ACTION_VOICE_INPUT_SETTINGS))
        }
        text(if(AiClient.configured(this))"Conexão com o serviço de IA preparada." else "A conexão de IA ainda está em preparação. Você pode configurar a chamada do assistente agora.")
        text("O microfone só abre ao tocar em Falar. O serviço de voz do Android pode processar áudio na nuvem. Não há escuta permanente.")
        button(if(checkSelfPermission(Manifest.permission.RECORD_AUDIO)==PackageManager.PERMISSION_GRANTED)"Voz autorizada" else "Permitir entrada por voz",R.id.assistant_voice_permission) {
            if(checkSelfPermission(Manifest.permission.RECORD_AUDIO)!=PackageManager.PERMISSION_GRANTED)requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO),52)
        }
        text("Antes de usar a IA, o painel pede autorização para enviar sua pergunta e rótulos dos controles à OpenAI. Campos preenchidos, senhas e imagens da tela não são enviados.")
        button("Voltar",R.id.assistant_setup_close) { finish() }
        setContentView(scroll)
    }
    override fun onRequestPermissionsResult(code: Int,permissions: Array<out String>,results: IntArray) { super.onRequestPermissionsResult(code,permissions,results);render() }
    override fun onActivityResult(request: Int,result: Int,data: Intent?) { super.onActivityResult(request,result,data);render() }
}
