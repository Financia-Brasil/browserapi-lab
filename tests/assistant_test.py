#!/usr/bin/env python3
"""Integração real em aparelho: contexto externo, consentimento, OpenAI e toque.
Requer beta pareado e escolhido como assistente. Usa somente dados fictícios.
"""
import argparse
import json
import time
from assistant_device import Device, PACKAGE, FIXTURE


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    phone = Device(args.serial, args.out)
    results = []

    def check(name, action):
        try:
            detail = action()
            results.append({"name": name, "status": "pass", "detail": detail or ""})
            print("PASS", name, flush=True)
        except Exception as exc:
            phone.shot("FALHA-assistente-"+str(len(results)))
            results.append({"name": name, "status": "fail", "detail": str(exc)})
            raise
        finally:
            (phone.out/"assistant-tests.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))

    def require(value, reason):
        if not value:
            raise AssertionError(reason)

    def rid(name):
        return PACKAGE+":id/assistant_"+name

    def evidence(name, data):
        (phone.out/name).write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def external_session():
        phone.fixture()
        phone.invoke()
        phone.wait_text("Farol", 10)
        require(phone.node(rid("panel")), "Painel do assistente ausente")
        state = phone.adb("shell", "dumpsys", "activity", "activities")
        tops = [line for line in state.splitlines() if "topResumedActivity=" in line or "mResumedActivity=" in line]
        require(any(FIXTURE in line for line in tops), "A atividade externa saiu do primeiro plano")
        evidence("foreground-session.json", {"activity": tops, "invocation": "KEYCODE_ASSIST"})
        phone.shot("03-painel-sobre-outro-app")
        return "KEYCODE_ASSIST abriu VoiceInteractionSession mantendo o exercício como atividade retomada"

    check("chamada do Android mantém aplicativo externo", external_session)

    def local_capture():
        phone.tap(rid("local"), scroll=True)
        phone.wait_text("Guia local", 10)
        payload = phone.private("last-assist-snapshot.json")
        require(payload["application"] == FIXTURE, "Captura pertence ao app errado")
        require(bool(payload["nodes"]), "Captura vazia não é prova")
        require(any(n["role"] == "textbox" for n in payload["nodes"]), "Campo não capturado")
        require(payload["consent"] == "local", "Guia local foi marcado como consulta de nuvem")
        evidence("assist-empty-sanitized.json", payload)
        phone.shot("04-guia-local-externo")
        return {"nodes": len(payload["nodes"]), "application": payload["application"]}

    check("guia local usa estrutura externa real e não vazia", local_capture)

    def real_ai():
        phone.hide()
        phone.invoke()
        if phone.node(rid("allow_cloud")):
            phone.tap(rid("allow_cloud"), scroll=True)
        else:
            # O consentimento pode estar abaixo do trecho visível do painel.
            text = phone.texts()
            if "Autorizar" in text or "autorização" in text:
                phone.tap(rid("allow_cloud"), scroll=True)
            else:
                phone.tap(rid("explain"), scroll=True)
        deadline = time.monotonic()+40
        result = None
        while time.monotonic()<deadline:
            try:
                result = phone.private("last-ai-result.json")
                if result.get("request_id", "").startswith("resp_"):
                    break
            except (RuntimeError, json.JSONDecodeError):
                pass
            time.sleep(1)
        require(result and result.get("provider") == "openai", "Nenhuma resposta real recebida no aparelho")
        require(result.get("request_id", "").startswith("resp_"), "Sem ID da resposta OpenAI")
        payload = phone.private("last-assist-snapshot.json")
        require(payload["consent"] == "cloud-v1", "Consentimento de nuvem ausente")
        ids = {n["id"] for n in payload["nodes"]}
        require(result["target_id"] is None or result["target_id"] in ids, "Alvo inventado")
        require(result["instruction"] in phone.texts(), "A resposta não apareceu no painel")
        evidence("openai-on-device.json", result)
        evidence("openai-device-payload.json", payload)
        phone.shot("05-openai-sobre-exercicio")
        return {"model": result["model"], "request_id": result["request_id"], "target_id": result["target_id"]}

    check("IA real responde no painel sobre outro aplicativo", real_ai)

    def filled_privacy():
        phone.hide()
        phone.fixture()
        phone.tap(FIXTURE+":id/fixture_cpf")
        phone.adb("shell", "input", "text", "12345678901")
        phone.adb("shell", "input", "keyevent", "4")
        phone.tap(FIXTURE+":id/fixture_password")
        phone.adb("shell", "input", "text", "S3gredoFarol2026")
        phone.adb("shell", "input", "keyevent", "4")
        phone.invoke()
        phone.tap(rid("local"), scroll=True)
        payload = phone.private("last-assist-snapshot.json")
        require(payload["application"] == FIXTURE and len(payload["nodes"]) >= 3, "Captura de privacidade vazia ou insuficiente")
        require(any(n["role"] == "textbox" and n["filled"] for n in payload["nodes"]), "CPF preenchido não foi observado")
        serialized = json.dumps(payload)
        for secret in ["12345678901", "S3gredoFarol2026", "contato-privado", "example.invalid"]:
            require(secret not in serialized, "Dado fictício privado vazou: "+secret)
        require(all(set(n) == {"id", "role", "label", "filled"} for n in payload["nodes"]), "Propriedade extra na captura")
        evidence("assist-filled-sanitized.json", payload)
        phone.shot("06-campos-preenchidos-saneados")
        return {"nodes": len(payload["nodes"]), "typed_values": "absent", "free_text": "absent"}

    check("campos preenchidos e texto livre ficam fora do contexto", filled_privacy)

    def user_controls():
        phone.hide()
        require("Exercício concluído" not in phone.texts(), "Farol enviou o formulário sozinho")
        phone.tap(FIXTURE+":id/fixture_continue")
        phone.wait_text("Exercício concluído", 10)
        phone.shot("07-acao-executada-pela-pessoa")
        return "Somente o toque explícito do teste no botão concluiu o exercício"

    check("somente o usuário executa a ação indicada", user_controls)

    def protected_screen():
        phone.fixture(secure=True)
        phone.invoke()
        phone.tap(rid("local"), scroll=True)
        payload = phone.private("last-assist-snapshot.json")
        require(payload["nodes"] == [], "Tela FLAG_SECURE forneceu conteúdo indevido")
        evidence("assist-protected-screen.json", payload)
        phone.shot("08-tela-protegida")
        return "FLAG_SECURE respeitado, contexto vazio"

    check("janela protegida não é contornada", protected_screen)
    phone.hide()
    print("Testes de integração concluídos.", flush=True)


if __name__ == "__main__":
    main()
