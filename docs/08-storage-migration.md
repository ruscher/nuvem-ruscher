# 08 — Trocar o local das fotos (migração)

Documento de trabalho; o app não lê este arquivo.

## O que o Immich exige (v3.2.4, conferido no código da tag)

- O container vê a biblioteca sempre em `/data` (`${UPLOAD_LOCATION}:/data`; no nosso
  override, bind com `create_host_path: false`). O banco guarda caminhos **do container**
  (`/data/library/…`). Mudar só a pasta do host **não exige** migração no banco.
- `immich-admin change-media-location` serve para quando o caminho **do container** muda
  (ex.: `/usr/src/app/upload` → `/data`). Não é o nosso caso, então não é usado.
- Na partida, o Immich lê e grava o marcador `.immich` de cada pasta (`library`, `upload`,
  `thumbs`, `encoded-video`, `profile`, `backups`) e **recusa subir** se faltar algum
  ("Missing volume mount"). É uma verificação extra de que a pasta certa foi montada.

## Modos

| Modo | Quando | O que faz |
|---|---|---|
| `copy` (padrão) | destino em outro disco ou mesmo disco com espaço | copia com `rsync`, verifica, troca, mantém a origem |
| `rename` | mesmo sistema de arquivos (mesmo ponto de montagem) | `rename(2)` atômico da pasta; nada é copiado (sem cópia antiga) |
| `adopt` | o destino **já contém** uma biblioteca do Immich (cópia feita antes) | só troca o local, depois de conferir marcadores e quantidade de arquivos |

"Usar o novo local sem mover" só existe como `adopt`: apontar o Immich para uma pasta vazia
deixaria o banco referenciando arquivos que não existem (miniaturas e originais quebrados).
Por isso a opção fica indisponível, com a explicação, quando o destino não tem uma biblioteca.

## Etapas do `migrate-storage` (helper, como root)

1. **check** — origem = `UPLOAD_LOCATION` atual; destino validado como na instalação
   (absoluto, sem `..`, sem caracteres especiais, fora de áreas do sistema, sem link
   simbólico no caminho). Recusa destino dentro da origem e origem dentro do destino. O
   destino precisa estar montado e com escrita; disco desconectado = `storage-missing`.
   Destino em `copy` precisa estar vazio (ou ser uma cópia interrompida **desta** migração,
   reconhecida pelo arquivo `.nuvem-ruscher-migration` com a origem dentro). FAT32 com
   arquivo > 4 GB, ou links simbólicos na origem indo para exFAT/FAT/NTFS: recusado antes
   de começar. Espaço: tamanho da origem + 2 % + 1 GiB.
2. **backup** — servidor tem que estar saudável; backup do banco (`pg_dump`, como o botão
   da página Backups) antes de qualquer cópia.
3. **copy** — `rsync` com o servidor **no ar** (a cópia longa não tira as fotos do ar).
   Progresso real (`--info=progress2`). Opções por sistema de arquivos do destino:
   Linux (`ext4`, `btrfs`, `xfs`, `f2fs`): `-aHAX --numeric-ids`; NTFS/exFAT/FAT:
   `-rlt` (dono e permissões vêm das opções de montagem) e `--modify-window` no FAT.
   **Único momento cancelável**: o app fecha o stdin do helper e ele interrompe o `rsync`;
   o servidor continua na origem, intacto.
4. **stop** — para o serviço (nenhuma gravação nova a partir daqui).
5. **sync** — segundo `rsync`, com `--delete` **só dentro do destino** (que é dedicado).
6. **verify** — mesma contagem de arquivos e de bytes; `rsync --dry-run --itemize-changes`
   sem nenhuma diferença; SHA-256 de uma amostra (os 20 maiores + 200 sorteados).
7. **switch** — `.env` (`UPLOAD_LOCATION`), configuração do app e unidade systemd
   (`BindsTo`/`RequiresMountsFor`/`ExecStartPre=mountpoint` do disco novo) reescritos com
   troca atômica; `daemon-reload`. A origem fica registrada como `OLD_UPLOAD_LOCATION`.
8. **start** — liga o serviço e espera o `/api/server/ping`.
9. **confirm** — dentro do container: `/data/upload/.immich` existe e `/data` aceita
   gravação (arquivo de teste criado e apagado). Só então o resultado é `migrated`.

Falha depois do passo 4: configuração, `.env` e unidade voltam para a origem, o serviço
religa na origem (`error migration-rolled-back`). A cópia nova fica onde está, para análise.
O app ignora o fechamento da janela a partir do passo 4 (o helper ignora `SIGPIPE`, segue
até o fim e grava o resultado em `/var/lib/nuvem-ruscher/migration.state`).

## Depois

O app mostra: *"A migração terminou e foi verificada. Manter a cópia antiga como backup ou
removê-la?"* — **Manter** (padrão), **Abrir o local antigo**, **Remover a cópia antiga**.

Remover (`remove-old-copy`) só funciona com o caminho exato registrado em
`OLD_UPLOAD_LOCATION`, que não pode ser o local atual nem estar dentro dele; refaz a
comparação (`rsync --dry-run`) antes; apaga só as pastas do Immich que foram copiadas
(`library`, `upload`, `thumbs`, `encoded-video`, `profile`, `backups`) com
`rm -r --one-file-system`, e só depois de uma confirmação que mostra o caminho e o tamanho.

## Rename (mesmo disco)

`stop` → `mv -T` da pasta (mesmo `st_dev` e mesmo ponto de montagem, conferidos) → `switch`
→ `start` → `confirm`. Falhou ao ligar: renomeia de volta e restaura a configuração.
