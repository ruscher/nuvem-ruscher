"""Protocolo de linhas do helper e tradução de erros para linguagem humana."""

from __future__ import annotations

from dataclasses import dataclass

from nuvem_ruscher.i18n import N_, _


@dataclass(frozen=True)
class HelperEvent:
    kind: str  # step, info, progress, result, error, log
    key: str = ""
    value: str = ""


def parse_line(line: str) -> HelperEvent:
    line = line.rstrip("\n")
    if not line.startswith("@@"):
        return HelperEvent("log", value=line)
    tag, _sep, rest = line[2:].partition(" ")
    tag = tag.lower()
    if tag == "result":
        key, _eq, value = rest.partition("=")
        return HelperEvent("result", key, value)
    if tag == "error":
        code, _sp, message = rest.partition(" ")
        return HelperEvent("error", code, message)
    if tag in ("step", "info", "progress"):
        return HelperEvent(tag, value=rest)
    return HelperEvent("log", value=line)


# código → (título, o que fazer)
ERRORS: dict[str, tuple[str, str]] = {
    "auth-cancelled": (
        N_("A autorização foi cancelada"),
        N_("Nada foi alterado. Tente de novo e digite a senha de administrador quando ela for pedida."),
    ),
    "not-authorized": (
        N_("Seu usuário não tem permissão de administrador"),
        N_("Peça para alguém com acesso de administrador abrir o Nuvem Ruscher e fazer esta etapa."),
    ),
    "helper-missing": (
        N_("O Nuvem Ruscher não está instalado por completo"),
        N_("Instale o pacote nuvem-ruscher (ou rode “sudo make install”) e abra o app de novo."),
    ),
    "invalid-argument": (
        N_("Um dado enviado não passou na verificação de segurança"),
        N_("Nada foi alterado. Confira a pasta escolhida e tente de novo."),
    ),
    "storage-missing": (
        N_("O disco das fotos não está conectado"),
        N_("Conecte o disco, espere ele aparecer no gerenciador de arquivos e tente de novo."),
    ),
    "storage-unsafe": (
        N_("A pasta das fotos não está num lugar seguro"),
        N_("Escolha uma pasta dentro de um disco montado. Nada foi alterado."),
    ),
    "download-failed": (
        N_("Não foi possível baixar os arquivos do Immich"),
        N_("Verifique a internet e tente de novo. O processo continua de onde parou."),
    ),
    "pacman-failed": (
        N_("A instalação de pacotes falhou"),
        N_("Atualize o sistema pela loja de programas (ou “sudo pacman -Syu”) e tente de novo."),
    ),
    "fstab-exists": (
        N_("Esse disco já tem uma regra de montagem"),
        N_("Ele já está configurado no sistema. Nenhuma alteração foi feita."),
    ),
    "fstab-invalid": (
        N_("A regra de montagem não passou na verificação"),
        N_("Nada foi alterado: o arquivo original foi restaurado automaticamente."),
    ),
    "unsupported-fs": (
        N_("Esse tipo de disco não pode ser montado automaticamente"),
        N_("O servidor ainda funciona, mas só depois que você entrar na sessão e abrir o disco."),
    ),
    "db-password-missing": (
        N_("Existe um banco de dados antigo sem a senha correspondente"),
        N_("Para não perder nada, a instalação parou. Veja os detalhes técnicos para recuperar."),
    ),
    "service-failed": (
        N_("O servidor não conseguiu ligar"),
        N_("Confira se o disco das fotos está conectado e veja os registros para mais detalhes."),
    ),
    "not-installed": (
        N_("O servidor ainda não foi instalado"),
        N_("Rode o assistente de instalação primeiro."),
    ),
    "not-running": (
        N_("O servidor está desligado"),
        N_("Ligue o servidor e tente de novo."),
    ),
    "backup-failed": (
        N_("O backup do banco de dados falhou"),
        N_("Confira o espaço livre no disco das fotos e tente de novo."),
    ),
    "update-rolled-back": (
        N_("A atualização não deu certo, mas tudo voltou como estava"),
        N_("Seu servidor continua na versão anterior, com todos os dados. Veja os detalhes técnicos."),
    ),
    "rollback-failed": (
        N_("A atualização falhou e a volta automática também"),
        N_("Suas fotos estão seguras no disco. Veja os detalhes técnicos: há uma cópia do banco guardada."),
    ),
    "no-space": (
        N_("Falta espaço no disco do sistema"),
        N_("Libere espaço e tente de novo."),
    ),
    "firewall-failed": (
        N_("Não foi possível ajustar o firewall"),
        N_("Você pode liberar a porta 2283 manualmente nas configurações do firewall."),
    ),
    "internal": (
        N_("Algo inesperado aconteceu"),
        N_("Nada nas suas fotos foi alterado. Veja os detalhes técnicos e tente de novo."),
    ),
}


def human_error(code: str) -> tuple[str, str]:
    title, hint = ERRORS.get(code, ERRORS["internal"])
    return _(title), _(hint)


def pkexec_error_code(returncode: int) -> str | None:
    """pkexec devolve 126 quando o diálogo é fechado e 127 quando não autorizado."""
    if returncode == 126:
        return "auth-cancelled"
    if returncode == 127:
        return "not-authorized"
    return None
