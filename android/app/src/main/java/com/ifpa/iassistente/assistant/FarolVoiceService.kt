package com.ifpa.iassistente.assistant

import android.os.Bundle
import android.service.voice.VoiceInteractionService
import android.service.voice.VoiceInteractionSession
import android.service.voice.VoiceInteractionSessionService

class FarolVoiceService : VoiceInteractionService() {
    companion object { var active: FarolVoiceService?=null; private set }
    override fun onReady() { super.onReady();active=this }
    override fun onShutdown() { if(active===this)active=null;super.onShutdown() }
}
class FarolSessionService : VoiceInteractionSessionService() {
    override fun onNewSession(args: Bundle?): VoiceInteractionSession = FarolSession(this)
}
