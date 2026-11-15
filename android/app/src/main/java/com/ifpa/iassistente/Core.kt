package com.ifpa.iassistente

import java.net.URI

object Privacy {
    private val email = Regex("[A-Z0-9._%+-]+@[A-Z0-9.-]+\\.[A-Z]{2,}", RegexOption.IGNORE_CASE)
    private val digits = Regex("\\b\\d[\\d.() /+\\-]{5,}\\d\\b")
    fun clean(text: String): String = digits.replace(email.replace(text, "[texto]"), "[texto]").take(180)
    fun origin(raw: String): String? = try {
        val uri = URI(raw)
        if (uri.scheme != "https" || uri.host.isNullOrBlank() || uri.rawUserInfo != null || uri.port !in listOf(-1, 443)) null
        else "https://" + uri.host.lowercase()
    } catch (_: Exception) { null }
}

data class Target(val index: Int, val role: String, val label: String, val filled: Boolean = false, val sensitive: Boolean = false)
data class Advice(val text: String, val target: Int? = null, val state: String = "Guia local", val detail: String = text)

object LocalPlanner {
    fun plan(nodes: List<Target>, error: String?, complete: Boolean = false): Advice {
        if (complete) return Advice("Treino concluído! Você fez cada ação no seu ritmo.", state = "Concluído")
        if (!error.isNullOrBlank()) {
            val e = error.lowercase()
            val text = when {
                "timeout" in e || "sessão expir" in e -> "O tempo desta sessão terminou. Volte e tente entrar novamente."
                "cpf" in e || "inválid" in e -> "Confira o campo indicado. O portal informou que o dado precisa ser revisado."
                "captcha" in e -> "O portal pede uma verificação de segurança. Faça a confirmação você mesmo."
                else -> "O portal mostrou um aviso. Leia a mensagem antes de continuar."
            }
            return Advice(text, nodes.firstOrNull { it.role == "alert" }?.index, "Aviso do portal", text + " O Farol não altera seus dados.")
        }
        val empty = nodes.firstOrNull { it.role in listOf("textbox", "combobox") && !it.filled }
        if (empty != null) {
            val name = empty.label.ifBlank { "indicado" }
            return Advice("Toque no campo $name e preencha no seu ritmo.", empty.index,
                detail = if (empty.sensitive) "Este campo é reservado. Digite você mesmo; o Farol não lê a senha."
                else "Procure o campo $name com a borda amarela. Toque nele e digite o que o portal pede.")
        }
        val button = nodes.firstOrNull { it.role == "button" }
        if (button != null) {
            return Advice("Quando estiver pronto, toque em “${button.label.ifBlank { "Continuar" }}”.", button.index,
                detail = "Confira o que você preencheu. Depois, toque no botão com a borda amarela. Você decide quando seguir.")
        }
        val link = nodes.firstOrNull { it.role == "link" }
        if (link != null) return Advice("Você pode abrir “${link.label}”. Leia antes de escolher.", link.index)
        return Advice("Leia o conteúdo desta página. Se precisar, toque em Explicar tela.", state = "Sem alvo disponível")
    }
}
