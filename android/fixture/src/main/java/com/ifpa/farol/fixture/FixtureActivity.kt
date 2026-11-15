package com.ifpa.farol.fixture

import android.app.Activity
import android.graphics.Color
import android.os.Bundle
import android.text.InputType
import android.view.WindowManager
import android.widget.*

class FixtureActivity:Activity() {
    override fun onCreate(saved:Bundle?) {
        super.onCreate(saved)
        if(intent.getBooleanExtra("secure",false))window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        val d=resources.displayMetrics.density
        fun dp(n:Int)=(n*d+.5f).toInt()
        val scroll=ScrollView(this)
        val box=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL;setPadding(dp(24),dp(24),dp(24),dp(24));setBackgroundColor(Color.WHITE) }
        scroll.addView(box)
        fun text(value:String,size:Float=18f){box.addView(TextView(this).apply{text=value;textSize=size;setTextColor(Color.rgb(4,24,63));setPadding(0,dp(8),0,dp(16))})}
        text("Exercício em outro aplicativo",26f)
        text("Formulário fictício para praticar com o Farol. Não use dados pessoais.")
        text("CPF de teste")
        val cpf=EditText(this).apply{id=R.id.fixture_cpf;hint="CPF de teste";contentDescription="CPF de teste";textSize=18f;minimumHeight=dp(56);inputType=InputType.TYPE_CLASS_NUMBER;importantForAutofill=android.view.View.IMPORTANT_FOR_AUTOFILL_NO}
        box.addView(cpf)
        text("Senha fictícia — não é enviada ao Farol")
        val password=EditText(this).apply{id=R.id.fixture_password;hint="Senha";textSize=18f;minimumHeight=dp(56);inputType=InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD;importantForAutofill=android.view.View.IMPORTANT_FOR_AUTOFILL_NO}
        box.addView(password)
        val result=TextView(this).apply{id=R.id.fixture_result;textSize=18f;setTextColor(Color.rgb(4,24,63))}
        box.addView(Button(this).apply{id=R.id.fixture_continue;text="Continuar";textSize=18f;isAllCaps=false;minimumHeight=dp(56);setOnClickListener{result.text=if(cpf.text.length==11)"Exercício concluído" else "Confira os 11 números fictícios"}})
        box.addView(result)
        text("Texto de teste: contato-privado@example.invalid. Esta frase livre não deve entrar no contexto do assistente.",16f)
        setContentView(scroll)
    }
}
