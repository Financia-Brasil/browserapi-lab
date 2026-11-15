package com.ifpa.iassistente

import org.junit.Assert.*
import org.junit.Test

class CoreTest {
    @Test fun originRejectsUnsafeAddresses() {
        listOf("http://gov.br","javascript:alert(1)","file:///etc/passwd","content://secret","https://me:secret@gov.br",
            "https://gov.br:8443","invalid","https://").forEach { assertNull(it,Privacy.origin(it)) }
    }
    @Test fun originRemovesQueryFragmentAndPath() {
        assertEquals("https://gov.br",Privacy.origin("https://gov.br/path/12345678901?cpf=12345678901#secret"))
    }
    @Test fun redactsIdentifiers() {
        listOf("123.456.789-01","12345678901","ana@example.com","+55 (91) 99999-1234","66000-000").forEach {
            assertFalse(it,Privacy.clean("Campo $it").contains(it))
        }
    }
    @Test fun cleanBoundsLongText() { assertEquals(180,Privacy.clean("a".repeat(500)).length) }
    @Test fun choosesUnfilledFieldBeforeButton() {
        val p=LocalPlanner.plan(listOf(Target(0,"button","Continuar"),Target(1,"textbox","CPF")),null)
        assertEquals(1,p.target); assertTrue(p.text.contains("CPF"))
    }
    @Test fun completedFieldMovesToButton() {
        val p=LocalPlanner.plan(listOf(Target(0,"textbox","CPF",true),Target(1,"button","Continuar")),null)
        assertEquals(1,p.target)
    }
    @Test fun passwordGetsPrivateExplanation() {
        val p=LocalPlanner.plan(listOf(Target(2,"textbox","Senha",false,true)),null)
        assertTrue(p.detail.contains("não lê a senha"))
    }
    @Test fun timeoutIsNotAccountLinkedError() {
        val p=LocalPlanner.plan(emptyList(),"ERR_SESSION_TIMEOUT")
        assertTrue(p.text.contains("tempo")); assertFalse(p.text.contains("aparelho"))
    }
    @Test fun invalidFieldProducesReviewInstruction() {
        val p=LocalPlanner.plan(listOf(Target(3,"alert","CPF inválido")),"CPF inválido")
        assertEquals(3,p.target); assertTrue(p.text.contains("Confira"))
    }
    @Test fun captchaRequiresUserAction() {
        assertTrue(LocalPlanner.plan(emptyList(),"captcha").text.contains("você mesmo"))
    }
    @Test fun emptyPageHasNoTarget() { assertNull(LocalPlanner.plan(emptyList(),null).target) }
    @Test fun completedTrainingHasNoTarget() {
        val p=LocalPlanner.plan(listOf(Target(1,"button","Reiniciar")),null,true)
        assertNull(p.target); assertEquals("Concluído",p.state)
    }
    @Test fun planNeverRequestsExecution() {
        val p=LocalPlanner.plan(listOf(Target(0,"button","Pagar")),null)
        assertTrue(p.text.contains("Quando estiver pronto"))
    }
}
