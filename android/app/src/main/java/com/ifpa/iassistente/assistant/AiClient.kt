package com.ifpa.iassistente.assistant

import android.content.Context
import android.net.Uri
import com.ifpa.iassistente.BuildConfig
import com.ifpa.iassistente.Privacy
import org.json.JSONObject
import java.io.File
import java.io.InputStream
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URL

class AiUnavailable(val code: String): Exception(code)
data class AiAdvice(val instruction: String,val detail: String,val target: Int?,val provider: String,val model: String,val requestId: String)

object AiClient {
    private fun limited(input: InputStream, limit: Int): ByteArray {
        val out=ByteArrayOutputStream();val buffer=ByteArray(4096)
        while(out.size()<=limit) {
            val count=input.read(buffer,0,minOf(buffer.size,limit+1-out.size()))
            if(count<0)break
            out.write(buffer,0,count)
        }
        if(out.size()>limit)throw AiUnavailable("invalid_response")
        return out.toByteArray()
    }
    fun configured(context: Context): Boolean = try { config(context); true } catch(_:Exception) { false }
    private fun config(context: Context): JSONObject {
        val config=JSONObject(File(context.filesDir,"ai-connection.json").readText())
        val endpoint=Uri.parse(config.getString("endpoint"))
        val loopback=BuildConfig.DEBUG && endpoint.scheme=="http" && endpoint.host in listOf("127.0.0.1","localhost")
        if((endpoint.scheme!="https" && !loopback) || endpoint.host.isNullOrBlank() || endpoint.userInfo!=null || endpoint.query!=null || endpoint.fragment!=null || config.getString("token").length<24)throw AiUnavailable("not_configured")
        return config
    }
    fun ask(context: Context,payload: JSONObject): AiAdvice {
        val config=try { config(context) }catch(_:Exception){throw AiUnavailable("not_configured")}
        val conn=URL(config.getString("endpoint")).openConnection() as HttpURLConnection
        try {
            conn.requestMethod="POST";conn.doOutput=true;conn.instanceFollowRedirects=false
            conn.connectTimeout=8000;conn.readTimeout=30000
            conn.setRequestProperty("Content-Type","application/json")
            conn.setRequestProperty("Authorization","Bearer "+config.getString("token"))
            conn.outputStream.use { it.write(payload.toString().toByteArray(Charsets.UTF_8)) }
            if(conn.responseCode!=200) {
                val body=conn.errorStream?.use { limited(it,4096).toString(Charsets.UTF_8) }.orEmpty()
                val error=try { JSONObject(body).optString("error") }catch(_:Exception){"http_"+conn.responseCode}
                throw AiUnavailable(error)
            }
            val raw=conn.inputStream.use { limited(it,16384) }
            val body=JSONObject(raw.toString(Charsets.UTF_8))
            val provider=body.getString("provider")
            if(provider!="openai")throw AiUnavailable("not_a_real_provider")
            val instruction=body.getString("instruction");val detail=body.getString("detail")
            if(instruction.isBlank() || instruction.length>240 || detail.length>400)throw AiUnavailable("invalid_response")
            val target=if(body.isNull("target_id")) null else body.getInt("target_id")
            val ids=payload.getJSONArray("nodes").let { ns -> (0 until ns.length()).map { ns.getJSONObject(it).getInt("id") } }
            if(target!=null && target !in ids)throw AiUnavailable("invalid_target")
            return AiAdvice(Privacy.clean(instruction,240),Privacy.clean(detail,400),target,provider,body.getString("model"),body.optString("request_id"))
        } finally { conn.disconnect() }
    }
}
