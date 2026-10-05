# 14 — Revisão de segurança (v2)

Documento de trabalho; o app não lê este arquivo.

## Modelo

- A interface roda como o usuário. Tudo o que precisa de root passa pelo
  `nuvem-ruscher-helper` via `pkexec`, com uma **lista fechada de ações** e argumentos
  validados de novo no helper (a interface nunca é a barreira).
- Ações sem senha na sessão ativa: `start`, `stop`, `restart` (sem argumentos) e
  `disk-health` (só leitura do SMART, caminhos de disco validados). O resto
  (`manage`, `auth_admin_keep`) pede a senha de administrador.
- O pkexec limpa o ambiente; o helper fixa `PATH=/usr/bin:/usr/sbin:/bin:/sbin`,
  `LC_ALL=C.UTF-8` e `umask 022`; o interpretador é `/usr/bin/bash`.

## Verificado nas partes novas

| Tema | Como está |
|---|---|
| Injeção de comando | Nenhum argumento vira shell: `"$var"` sempre, `--` antes de caminhos, `validate_choice`/regex em modos, níveis, séries e caminhos de disco. Python sem `shell=True`. |
| Caminhos | `validate_path` (o mesmo de antes) + recusa de pastas que só agrupam outras (`/home`, `/home/<usuário>`, `/mnt`, `/media`, `/run/media/<usuário>`, `/var`, `/var/lib`, `/opt`, `/srv`). Origem e destino não podem estar um dentro do outro. |
| Links simbólicos | Recusados no caminho da pasta de fotos (setup e migração: `realpath` do pai), na pasta de backups e no destino. `remove-old-copy` confere `! -L` logo antes do `rm`; e `rm` sobre um link remove só o link. O `rsync` substitui links plantados no destino em vez de segui-los. |
| Remoções | Só duas recursivas no helper, ambas `--one-file-system --preserve-root=all`: o snapshot do banco e as seis pastas do Immich da cópia antiga — esta só com o caminho exato de `OLD_UPLOAD_LOCATION`, estado `migrated` e nova comparação (`rsync --dry-run --size-only`) sem diferenças. Todo `rm` novo usa `${var:?}`. |
| Operação destrutiva (RAID) | Discos inteiros por `/dev/disk/by-id` + lista de séries que o usuário confirmou; recusa disco do sistema, das fotos, do banco, do Docker, de swap, montado, LUKS, LVM, md, com holders; **falha fechada** se não identificar o disco do sistema. Testado: nenhuma chamada a `wipefs`/`mdadm`/`mkfs` em todos os casos recusados. |
| Concorrência | `flock` em `/run/nuvem-ruscher-helper.lock` (uma operação por vez). |
| Interrupção | Migração: cancelar só por pedido explícito no stdin e só durante a cópia; janela fechada/`SIGPIPE` não derrubam o helper; qualquer saída antes do fim volta configuração, `.env`, unidade (e a renomeação) e religa o servidor (EXIT trap). |
| Segredos | Cópias de `.env` só em `/var/lib/nuvem-ruscher/tmp` (700, root) e apagadas ao fim de uma migração bem-sucedida. Sessão do Immich só na memória, `logout` ao fechar. Senhas temporárias geradas com `secrets`, mostradas uma vez, nunca gravadas nem registradas em log. |
| URLs da API | IDs de usuário/álbum validados como UUID antes de entrar no caminho; parâmetros por `urlencode`; papéis só `editor`/`viewer` (nunca `owner`). |
| Disco sumiu | Inalterado: `BindsTo`/`RequiresMountsFor`, `ExecStartPre=mountpoint -q` e `create_host_path: false` valem para o novo local (inclusive `/mnt/nuvem-ruscher-raid`); testado na migração. |

## Achados e correções desta rodada

1. **Proteção do disco do sistema podia falhar aberta** (sandbox com espaço no caminho:
   o `awk` cortava o caminho e nenhum disco era protegido). Em discos reais não há espaço
   em `/dev/...`, mas a proteção agora lê `TYPE PATH` com `read` e **recusa** se não achar
   o disco do sistema. Teste `test_unknown_system_disk_fails_closed`.
2. **`/home` e `/home/<usuário>` eram aceitos** como pasta das fotos. Recusados (Python e helper).
3. **Backups com o mesmo segundo colidiam** (recusa segura, mas quebrava uma migração
   retomada). Nome livre com sufixo numérico.
4. **Cópias do `.env` após migração** — apagadas no sucesso (mantidas na falha, para
   recuperação manual).
5. Números de série com espaço eram recusados: a interface agora normaliza como o helper.

## Fora do escopo / limites conhecidos

- Um administrador que já digitou a senha pode, por definição, fazer o que quiser como root;
  as checagens contra TOCTOU no caminho das fotos são defesa em profundidade, não barreira.
- O Immich expõe a porta 2283 na rede local (decisão do Immich); a liberação do firewall é
  só para redes locais e Tailscale.
