package com.ifpa.iassistente.assistant

import android.Manifest
import android.app.Activity
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.speech.RecognitionListener
import android.speech.RecognitionService
import android.speech.SpeechRecognizer

open class SpeechListener : RecognitionListener {
    override fun onReadyForSpeech(params: Bundle?) {}
    override fun onBeginningOfSpeech() {}
    override fun onRmsChanged(rmsdB: Float) {}
    override fun onBufferReceived(buffer: ByteArray?) {}
    override fun onEndOfSpeech() {}
    override fun onError(error: Int) {}
    override fun onResults(results: Bundle?) {}
    override fun onPartialResults(partialResults: Bundle?) {}
    override fun onEvent(eventType: Int,params: Bundle?) {}
}
object FarolSpeech {
    fun rememberEngine(context: Context) {
        val value=Settings.Secure.getString(context.contentResolver,"voice_recognition_service")
        if(!value.isNullOrBlank() && !value.startsWith(context.packageName+"/"))
            context.getSharedPreferences("farol",Context.MODE_PRIVATE).edit().putString("original_recognizer",value).apply()
    }
    fun create(context: Context): SpeechRecognizer {
        val prefs=context.getSharedPreferences("farol",Context.MODE_PRIVATE)
        val saved=prefs.getString("original_recognizer",null)
        val component=saved?.let { ComponentName.unflattenFromString(it) }
        return if(component!=null && component.packageName!=context.packageName)SpeechRecognizer.createSpeechRecognizer(context,component)
        else {
            val own=context.packageName
            val service=context.packageManager.queryIntentServices(Intent("android.speech.RecognitionService"),0)
                .firstOrNull { it.serviceInfo.packageName!=own }?.serviceInfo
                ?: throw IllegalStateException("speech_unavailable")
            SpeechRecognizer.createSpeechRecognizer(context,ComponentName(service.packageName,service.name))
        }
    }
}
/** Serviço declarado pelo contrato de assistente; delega ao reconhecedor já escolhido. */
class FarolRecognitionService : RecognitionService() {
    private var engine: SpeechRecognizer?=null
    override fun onStartListening(intent: Intent,callback: Callback) {
        if(checkSelfPermission(Manifest.permission.RECORD_AUDIO)!=PackageManager.PERMISSION_GRANTED) {
            callback.error(SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS);return
        }
        try {
            engine?.destroy();engine=FarolSpeech.create(this)
            engine?.setRecognitionListener(object : SpeechListener() {
                override fun onReadyForSpeech(params: Bundle?) { callback.readyForSpeech(params ?: Bundle()) }
                override fun onBeginningOfSpeech() { callback.beginningOfSpeech() }
                override fun onRmsChanged(rmsdB: Float) { callback.rmsChanged(rmsdB) }
                override fun onBufferReceived(buffer: ByteArray?) { if(buffer!=null)callback.bufferReceived(buffer) }
                override fun onEndOfSpeech() { callback.endOfSpeech() }
                override fun onError(error: Int) { callback.error(error) }
                override fun onResults(results: Bundle?) { callback.results(results ?: Bundle()) }
                override fun onPartialResults(partialResults: Bundle?) { callback.partialResults(partialResults ?: Bundle()) }
            })
            engine?.startListening(intent)
        }catch(_:Exception){callback.error(SpeechRecognizer.ERROR_CLIENT)}
    }
    override fun onStopListening(callback: Callback) { engine?.stopListening() }
    override fun onCancel(callback: Callback) { engine?.cancel();engine?.destroy();engine=null }
    override fun onDestroy() { engine?.destroy();super.onDestroy() }
}
class VoicePermissionActivity : Activity() {
    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        if(checkSelfPermission(Manifest.permission.RECORD_AUDIO)==PackageManager.PERMISSION_GRANTED)complete(true)
        else requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO),71)
    }
    override fun onRequestPermissionsResult(request: Int,permissions: Array<out String>,results: IntArray) {
        super.onRequestPermissionsResult(request,permissions,results)
        complete(results.firstOrNull()==PackageManager.PERMISSION_GRANTED)
    }
    private fun complete(granted: Boolean) {
        finish()
        if(granted)Handler(Looper.getMainLooper()).postDelayed({
            FarolVoiceService.active?.showSession(Bundle().apply { putBoolean("listen",true) },android.service.voice.VoiceInteractionSession.SHOW_WITH_ASSIST)
        },600)
    }
}
