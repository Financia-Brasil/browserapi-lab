package com.ifpa.iassistente.assistant

import android.app.assist.AssistStructure
import android.graphics.RectF
import android.text.InputType
import android.view.View
import org.json.JSONArray
import org.json.JSONObject

class AssistSnapshot(val application: String, val nodes: JSONArray, val bounds: Map<Int,RectF>) {
    fun envelope(question: String): JSONObject = JSONObject().put("version",1)
        .put("application",application).put("question",com.ifpa.iassistente.Privacy.clean(question,400))
        .put("nodes",nodes).put("consent","cloud-v1")
}

object AssistCapture {
    fun capture(structure: AssistStructure?): AssistSnapshot {
        val nodes=JSONArray();val bounds=linkedMapOf<Int,RectF>();var visited=0
        val app=structure?.activityComponent?.packageName ?: "unknown"
        fun walk(n: AssistStructure.ViewNode,x: Int,y: Int,depth: Int) {
            if(depth>25 || visited++>=900 || nodes.length()>=60 || n.visibility!=View.VISIBLE || n.isAssistBlocked)return
            val left=x+n.left;val top=y+n.top
            val clazz=n.className.orEmpty()
            val field=clazz.contains("EditText") || n.inputType!=InputType.TYPE_NULL
            val variation=n.inputType and InputType.TYPE_MASK_VARIATION
            val inputClass=n.inputType and InputType.TYPE_MASK_CLASS
            val password=field && ((inputClass==InputType.TYPE_CLASS_TEXT && variation in setOf(InputType.TYPE_TEXT_VARIATION_PASSWORD,InputType.TYPE_TEXT_VARIATION_WEB_PASSWORD,InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD)) || (inputClass==InputType.TYPE_CLASS_NUMBER && variation==InputType.TYPE_NUMBER_VARIATION_PASSWORD))
            val candidate=if(field)n.hint else n.text?.toString() ?: n.contentDescription?.toString()
            val button=clazz.contains("Button")
            val include=field || button || AssistPolicy.known(candidate)
            if(include && n.width>0 && n.height>0) {
                val id=nodes.length()
                val role=if(field)"textbox" else if(button || n.isClickable)"button" else "text"
                nodes.put(JSONObject().put("id",id).put("role",role).put("label",AssistPolicy.label(candidate,field,password))
                    .put("filled",if(field && !password) !n.text.isNullOrEmpty() else false))
                bounds[id]=RectF(left.toFloat(),top.toFloat(),(left+n.width).toFloat(),(top+n.height).toFloat())
            }
            for(i in 0 until n.childCount)walk(n.getChildAt(i),left-n.scrollX,top-n.scrollY,depth+1)
        }
        if(structure!=null)for(i in 0 until structure.windowNodeCount) {
            val window=structure.getWindowNodeAt(i)
            walk(window.rootViewNode,window.left,window.top,0)
        }
        return AssistSnapshot(app,nodes,bounds)
    }
}
