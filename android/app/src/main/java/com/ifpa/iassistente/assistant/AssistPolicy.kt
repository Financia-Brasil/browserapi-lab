package com.ifpa.iassistente.assistant

import com.ifpa.iassistente.Privacy
import java.util.Locale

/** Rótulos desconhecidos são genéricos: textos de conversa e valores não viram contexto. */
object AssistPolicy {
    private val allowed = setOf(
        "continuar", "avançar", "voltar", "cancelar", "entrar", "sair", "salvar", "enviar", "confirmar",
        "ok", "sim", "não", "fechar", "abrir", "pesquisar", "buscar", "cpf", "cpf de teste", "senha",
        "e-mail", "email", "nome", "telefone", "conexões", "configurações", "wi-fi", "wifi", "internet",
        "bluetooth", "som", "sons e vibração", "notificações", "visor", "aplicativos", "acessibilidade",
        "segurança e privacidade", "sobre o telefone", "contas e backup", "gerenciamento geral",
        "começar", "começar treino", "começar exercício", "tentar novamente", "campo obrigatório",
        "ver detalhes", "próximo", "repetir", "ajuda", "permitir", "não permitir", "recusar", "aceitar"
    )
    fun label(candidate: String?, field: Boolean, password: Boolean = false): String {
        if (password) return "Senha"
        val text = Privacy.clean(candidate.orEmpty()).trim()
        if (text.lowercase(Locale.ROOT) in allowed) return text
        return if (field) "Campo de texto" else "Controle"
    }
    fun known(candidate: String?): Boolean = Privacy.clean(candidate.orEmpty()).trim().lowercase(Locale.ROOT) in allowed
}
