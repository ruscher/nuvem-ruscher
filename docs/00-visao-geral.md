# 00 — Visão geral

## Objetivo

O **Nuvem Ruscher** transforma um computador com BigLinux na “nuvem de fotos” da
família: instala, configura e cuida do [Immich](https://immich.app) (alternativa
livre e auto-hospedada ao Google Fotos) rodando em Docker, e deixa o celular Android
pronto para enviar as fotos automaticamente.

A promessa: **em poucos minutos, sem terminal, sem jargão e sem nenhum risco para as
fotos que já existem no disco.**

## Público

- **Principal:** pessoa leiga que usa BigLinux em casa, tem um HD externo/interno com
  espaço sobrando e quer parar de pagar armazenamento na nuvem. Não sabe o que é
  Docker, fstab ou systemd — e não precisa saber.
- **Secundário:** usuário técnico que quer um Immich bem montado (versão fixada,
  banco no SSD, montagem por UUID, backups, rollback) sem gastar uma tarde nisso.
  Para ele, cada tela tem um expansor “Detalhes técnicos”.

## Princípios

1. **As fotos são sagradas.** Nada é apagado, formatado ou movido no disco de fotos.
   Na dúvida, o app para e explica.
2. **Funciona depois de reiniciar.** O servidor só sobe com o disco certo montado no
   lugar certo, e sobe sozinho quando ele está.
3. **Honestidade amigável.** Limitações (ex.: NTFS) são ditas com clareza e sem
   alarmismo, junto com o que fazer.
4. **Nada trava a tela.** Toda operação demorada roda em segundo plano, com progresso
   real e possibilidade de cancelar.
5. **Privilégio mínimo.** A interface roda como usuário comum; um único auxiliar,
   chamado via `pkexec`, executa uma lista fechada de ações validadas.

## Jornada completa do usuário

```
 Menu do sistema ─► Nuvem Ruscher
        │
        ▼
 1. Boas-vindas ──── “Suas fotos, na sua casa.”  [Começar]
        │
        ▼
 2. Verificação ──── checklist animado: Docker instalado? rodando? você no grupo?
        │            memória? espaço? porta 2283? internet? firewall?
        │            cada item com problema tem um botão de correção.
        ▼
 3. Armazenamento ── “Suas fotos vão ficar em: Novo volume (1,8 TB livres)”
        │            aviso amigável sobre NTFS + oferta de montagem automática
        │            no boot (com consentimento e explicação).
        ▼
 4. Configuração ─── fuso horário e versão do Immich detectados;
        │            “Opções avançadas” recolhidas (GPU, inteligência artificial).
        ▼
 5. Instalação ───── etapas com progresso real: preparar → baixar (MB/s) →
        │            ligar → aguardar ficar saudável. Cancelável e retomável.
        ▼
 6. Conta ────────── nome, e-mail e senha do administrador, criados direto no app.
        │            (Se já existe conta de uma instalação anterior, pula.)
        ▼
 7. Celular ──────── QR para instalar o app + QR/endereço do servidor + dicas
        │            (bateria, pasta Câmera). Tailscale, se houver.
        ▼
 8. Celebração ───── confete sutil, “Sua nuvem está no ar!”  [Abrir o Immich]
        │
        ▼
 Execuções seguintes: Painel
   ├─ Visão geral: status ao vivo, containers, CPU/RAM, disco, nº de fotos/vídeos
   ├─ Celular: QR e endereço novamente (rede local e Tailscale)
   ├─ Registros: logs ao vivo com filtro e copiar
   ├─ Backups: lista dos backups do banco + “Fazer backup agora”
   ├─ Atualizações: novidades, alertas de mudanças incompatíveis, atualização
   │  com backup, verificação de saúde e rollback automático
   └─ Mais: acesso fora de casa, montagem automática, desinstalar (sem tocar
      nas fotos)
```

### Depois de reiniciar o computador

1. O systemd monta o disco de fotos por UUID **no mesmo caminho**
   (`/run/media/ruscher/Novo volume`) — se o usuário aceitou a montagem automática.
2. A unidade `nuvem-ruscher-immich.service` só inicia depois da montagem
   (`BindsTo=` + `RequiresMountsFor=` + verificação `mountpoint`).
3. Se o disco não estiver presente, o serviço **não sobe** (e nenhuma pasta vazia é
   criada no lugar errado). Quando o disco é conectado e montado, o serviço sobe
   sozinho.
4. O celular volta a sincronizar sem nenhuma ação do usuário.

## O que é “pronto” para o usuário

- `http://localhost:2283` responde e a conta de administrador existe.
- As fotos enviadas pelo celular aparecem em
  `/run/media/ruscher/Novo volume/immich-ruscher/`.
- O banco de dados está em `/var/lib/nuvem-ruscher/immich/postgres` (disco interno).
- Após reiniciar, tudo volta sozinho; sem o disco, nada sobe.

## Ideias extras implementadas (além do enunciado)

| Ideia | Por quê |
|---|---|
| Serviço sobe sozinho quando o disco é conectado (`.wants` da unidade de montagem) | Quem não aceitou o fstab também tem servidor automático |
| `create_host_path: false` no bind de `/data` | Terceira barreira: o Docker nunca cria a pasta de fotos vazia |
| Snapshot do banco antes de atualizar (`cp --reflink`, instantâneo em btrfs) | Rollback em segundos, sem depender só do dump |
| `docker events` para status ao vivo | Zero polling quando nada muda |
| Dois QR codes (loja + endereço) | O app Immich não lê QR; o celular abre/copia o endereço |
| Detecção de biblioteca existente + caminho de restauração oficial | Reinstalar nunca “perde” fotos |
| Liberação opcional da porta no ufw/firewalld | O BigLinux pode vir com firewall ativo |
| Docker usado via `sg docker` logo após entrar no grupo | Não obriga sair da sessão |
| Modo `--simular` com cenários (`--cenario ntfs`, `sem-docker`, …) | Demonstração e QA sem tocar no sistema |
