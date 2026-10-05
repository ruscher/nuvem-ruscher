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

## Segunda revisão (diff completo `main...feat/v2`)

Três revisões independentes (helper, núcleo/backend, interface). Corrigido:

1. **`remove-old-copy` apagava se a comparação falhasse.** `rsync … | head || true` jogava
   fora o código de saída: rsync ausente, erro de E/S ou de permissão viravam “sem
   diferenças”. Agora qualquer falha do rsync recusa, e falta de uma pasta do Immich no
   local atual também. Teste `test_refuses_when_the_comparison_fails`.
2. **A mesma pasta por dois caminhos** (bind mount, subvolume montado duas vezes) se
   comparava consigo mesma. Origem/destino e cópia antiga/atual agora são comparados por
   dispositivo + inode (`same_dir`), também pasta a pasta no adotar e no remover.
3. **Retomada podia apagar envios novos.** Depois da verificação, o marcador de cópia
   retomável sai *antes* da troca: se o servidor chegou a usar a pasta nova e a migração
   voltou, uma nova tentativa pede para adotar em vez de retomar com `--delete`.
4. **Disco das fotos desmontado aparecia livre para o RAID** (Python e helper). Agora ficam
   protegidos, montados ou não: o UUID gravado do disco das fotos e o da cópia antiga
   (`PHOTO_FS_UUID`, `OLD_PHOTO_FS_UUID`), o rótulo/UUID que o udisks usa em
   `/run/media/<usuário>/<nome>` (cobre instalações da v1) e todo disco citado no
   `/etc/fstab`. Membros de ZFS/bcache e discos de um btrfs montado em outro disco (mesmo
   UUID) também. Se o `lsblk` falhar, recusa (falha fechada).
5. **A origem sumindo no meio da cópia** (disco caiu) deixaria origem e cópia vazias e
   “iguais”. As pastas do Immich anotadas no começo precisam continuar existindo na origem e
   no destino antes da troca, e a confirmação dentro do container exige uma delas.
6. Remoção da cópia antiga feita de dentro da pasta (`cd -P` + caminhos relativos): trocar
   o caminho por um link depois da conferência não desvia o `rm`.
7. Planejamento alinhado ao helper: espaço livre 0/desconhecido bloqueia; adotar com menos
   de 98% dos arquivos é problema, não aviso. Retomada pede só o espaço que falta.
8. Interface: o diálogo da conta não gravava nada (argumentos nomeados não chegavam à
   chamada); “Personalizado” gravava 1 GB na hora; cliques no número viravam várias
   gravações fora de ordem; o interruptor de administrador não voltava após erro; o papel de
   um membro não voltava após erro; “Remover cópia antiga” e “Desinstalar” podiam rodar duas
   vezes; desinstalar com falha deixava o painel parado; desinstalar com sucesso quebrava
   (atributo renomeado). Testes de fumaça novos para conta, quota e desinstalação.
9. API: erros de protocolo HTTP e respostas fora do formato viram `ApiError` em vez de
   derrubar a página Contas. RAID 10 sem um par inteiro aparece como “falhou”.

Conferido contra a OpenAPI v3.2.4 (e mantido): `GET /albums` aceita `isOwned`/`isShared`;
`AlbumUserRole` inclui `owner`; partners têm `inTimeline` (texto da interface ajustado:
o parceiro *pode* mostrar as fotos na própria linha do tempo).

## Fora do escopo / limites conhecidos

- Um administrador que já digitou a senha pode, por definição, fazer o que quiser como root;
  as checagens contra TOCTOU no caminho das fotos são defesa em profundidade, não barreira.
- O Immich expõe a porta 2283 na rede local (decisão do Immich); a liberação do firewall é
  só para redes locais e Tailscale.
- Queda de energia ou `SIGKILL` no meio de uma migração deixa o servidor desligado e o
  estado em `running` (nada se perde; o app mostra a mudança não concluída). Não há
  recuperação automática no boot.
- A senha copiada fica na área de transferência até ser substituída.
- O prazo de exclusão de contas desativadas aparece como 7 dias (padrão do Immich); um
  servidor com `user.deleteDelay` alterado mostra o número errado.
