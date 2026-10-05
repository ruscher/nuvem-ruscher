# 09 — Redundância (RAID)

Documento de trabalho; o app não lê este arquivo.

## Conceitos na interface

- **Local das fotos**: onde a biblioteca está (uma pasta).
- **Redundância**: como os discos dessa pasta estão organizados. Um RAID novo vira um
  **disco novo e vazio**; levar as fotos para ele é uma migração (doc 08). Os dois fluxos
  nunca se misturam.
- Em toda tela de RAID: *"RAID protege contra a falha de alguns discos. RAID não é backup."*

## Mecanismo

`mdadm` (RAID por software do Linux): padrão em Arch/Manjaro/BigLinux, monta pelo udev no
boot sem initramfs (o array não guarda o sistema), funciona com qualquer sistema de
arquivos. Btrfs/ZFS RAID ficaram de fora: ZFS não está nos repositórios oficiais e o RAID5/6
do Btrfs ainda é desaconselhado pelos próprios desenvolvedores.

Sistema de arquivos do array: **ext4** (o mais testado com o Immich; o banco não vai para
ele — continua em `/var/lib/nuvem-ruscher`).

## Níveis oferecidos

| Nível | Discos | Uso | Na interface |
|---|---|---|---|
| RAID 1 | 2 (ou mais) | tamanho de 1 disco | **Recomendado** para casa |
| RAID 5 | 3+ | n−1 discos | Avançado: sobrevive a 1 falha; reconstrução longa e arriscada em discos grandes |
| RAID 6 | 4+ | n−2 discos | Avançado: sobrevive a 2 falhas |
| RAID 10 | 4+ (par) | metade | Avançado: rápido, sobrevive a 1 falha por par |
| RAID 0 | 2+ | soma | Só em Avançado, com aviso: *"RAID 0 não tem redundância. A falha de qualquer disco pode tornar todo o array indisponível."* |

Discos de tamanhos diferentes: o array usa o tamanho do menor (mostrado no resumo).

## Proteções antes de criar (helper `raid-create`)

O app só lista discos **inteiros**, identificados por `/dev/disk/by-id/…` + modelo + série
(nunca só `/dev/sdX`, que muda de ordem). O helper refaz todas as checagens como root e
recusa um disco que:

- contenha `/`, `/boot`, `/efi`, swap, ou qualquer partição montada;
- seja o disco da pasta das fotos atual, do banco (`/var/lib/nuvem-ruscher`) ou do Docker
  (`/var/lib/docker`);
- seja membro de RAID (`linux_raid_member`), volume LVM (`LVM2_member`), LUKS
  (`crypto_LUKS`), Btrfs com vários dispositivos, ou esteja em uso (holders em `/sys`);
- seja removível de leitura (`ro`).

Assinaturas existentes (partições, sistemas de arquivos) **não bloqueiam**, mas aparecem
destacadas ("Contém dados") e entram na confirmação.

A confirmação exige o argumento `--erase=<série1>,<série2>…`: o helper só apaga se a lista
de séries recebida for exatamente a dos discos escolhidos. A interface só monta esse
argumento depois de o usuário marcar, disco por disco, "Apagar tudo em <modelo> (<série>)"
e digitar o nome do array.

Sequência: `wipefs -a` em cada disco → `mdadm --create --metadata=1.2 --name=nuvem-ruscher`
→ espera o `/dev/md/nuvem-ruscher` → `mkfs.ext4 -L nuvem-ruscher` → linha `ARRAY` no
`/etc/mdadm.conf` (com cópia de segurança) → ponto de montagem
`/mnt/nuvem-ruscher-raid` → linha no `/etc/fstab` pelo UUID (`nofail`,
`x-systemd.device-timeout`, mesmo fluxo backup → verify → rollback do `fstab-add`) → monta.
A sincronização inicial roda em segundo plano; o array já pode ser usado.

## Saúde (sem root)

`/proc/mdstat` e `/sys/block/mdX/md/*` (`level`, `raid_disks`, `degraded`, `sync_action`,
`sync_completed`, `array_state`, `dev-*/state`). Estados mostrados com ícone **e** texto:

| Estado | Condição |
|---|---|
| Saudável | `degraded=0`, `sync_action=idle` |
| Reconstruindo / Verificando | `sync_action` = `recover`/`resync`/`reshape` / `check`/`repair` (com %) |
| Degradado | `degraded>0` e sem reconstrução |
| Falhou | `array_state` = `inactive`/`broken`/`failed`, ou faltam discos além da redundância |

Um array que some (discos desconectados) desmonta o ponto de montagem → a unidade do
Immich tem `BindsTo=` da montagem e `ExecStartPre=mountpoint`, e o bind usa
`create_host_path: false`: o servidor para em vez de gravar numa pasta vazia do disco do
sistema. Testado no simulador e no sandbox do helper.

## Testes

Nunca se cria RAID real nos testes: `mdadm`, `wipefs`, `mkfs.ext4`, `lsblk`, `blkid` são
comandos falsos no sandbox (`tests/sim-bin`), e o parser lê fixtures de `/proc/mdstat`.
