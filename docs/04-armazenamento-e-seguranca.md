# 04 — Armazenamento e segurança

## O disco de fotos desta máquina (detectado em 04/10/2026)

| Item | Valor |
|---|---|
| Dispositivo | `/dev/sdd1` (disco `sdd`, 1,8 TB) |
| Rótulo | `Novo volume` |
| UUID | `F22A6D342A6CF74F` |
| Sistema de arquivos | `ntfs` (montado pelo udisks2 com ntfs-3g → `fuseblk`) |
| Ponto de montagem | `/run/media/ruscher/Novo volume` (automático, por sessão) |
| Pasta do Immich | `/run/media/ruscher/Novo volume/immich-ruscher` (existe, vazia) |

## Detecção

1. `findmnt -J -T <pasta>` → ponto de montagem, dispositivo, tipo e opções.
2. `lsblk -J -b -o NAME,PATH,UUID,LABEL,FSTYPE,SIZE,FSAVAIL,FSUSED,MOUNTPOINTS,RM,HOTPLUG,ROTA,TRAN,MODEL <dispositivo>`
   → UUID, rótulo, tamanho, livre, se é removível/USB, modelo.
3. `fuseblk` é traduzido para o FS real pelo `FSTYPE` do lsblk (ex.: `ntfs`).
4. Biblioteca existente: arquivos `.immich` em `library/`, `upload/`, `thumbs/`,
   `encoded-video/`, `profile/`, `backups/` dentro da pasta.

Tudo é só leitura e roda como usuário comum.

## Caminho com espaço — onde e como é escapado

| Lugar | Forma | Teste |
|---|---|---|
| Bash | sempre `"$var"`; nunca `eval`/`source` de dados | `shellcheck` + testes do helper com espaço |
| Python | listas de argumentos (`subprocess` sem `shell=True`); `shlex.join` só para `sg -c` | `test_docker.py` |
| `.env` | `UPLOAD_LOCATION="/run/media/ruscher/Novo volume/immich-ruscher"` | `docker compose config` em teste |
| YAML (override) | não contém o caminho: usa `${UPLOAD_LOCATION}` | idem |
| systemd | `RequiresMountsFor="…"`, `ExecStartPre=… "…"`, unidade de montagem `run-media-ruscher-Novo\x20volume.mount` (`systemd-escape -p --suffix=mount`) | `systemd-analyze verify` em teste |
| fstab | `/run/media/ruscher/Novo\040volume` | `findmnt --tab-file` relê e compara |
| conf do app | `CHAVE=valor` cru, lido linha a linha (nunca com `source`) | `test_config.py` |

Caracteres **recusados** em caminhos (Python e Bash): controle/nova linha, `"`, `$`,
`` ` ``, `\`, `%` (especificador do systemd). Também recusa `..`, caminhos relativos
e áreas do sistema (`/`, `/etc`, `/usr`, `/boot`, `/proc`, `/sys`, `/dev`,
`/var/lib/docker`, `/var/lib/nuvem-ruscher`…).

## Montagem persistente no boot (fstab)

**Por que:** `/run/media/…` só existe depois que a sessão monta o disco. No boot, antes
do login, o caminho não existe.

**Oferta ao usuário (com consentimento explícito):**
> **Ligar o disco junto com o computador.** Assim o servidor de fotos funciona logo
> depois de reiniciar, mesmo antes de você entrar na sessão. O disco continua
> aparecendo no mesmo lugar de sempre. Se ele não estiver conectado, o computador
> liga normalmente.

**Linha gerada (NTFS):**
```
# Nuvem Ruscher: disco de fotos do Immich (adicionado em 2026-10-04)
UUID=F22A6D342A6CF74F /run/media/ruscher/Novo\040volume ntfs-3g defaults,nofail,nosuid,nodev,uid=1000,gid=1007,dmask=022,fmask=133,windows_names,x-systemd.device-timeout=15s 0 0
```

**Opções por sistema de arquivos:**

| FS | tipo | opções (além de `defaults,nofail,nosuid,nodev,x-systemd.device-timeout=15s`) | passo |
|---|---|---|---|
| ntfs | `ntfs-3g` | `uid,gid,dmask=022,fmask=133,windows_names` | 0 |
| exfat | `exfat` | `uid,gid,dmask=022,fmask=133` | 0 |
| vfat | `vfat` | `uid,gid,dmask=022,fmask=133,utf8,shortname=mixed` | 0 |
| ext4/ext3/xfs/f2fs | o próprio | `noatime` | 2 |
| btrfs | `btrfs` | `noatime` (+ `subvol=` atual, se houver) | 0 |

`uid`/`gid` vêm do usuário que pediu (`PKEXEC_UID`), para que os arquivos continuem
“seus” no gerenciador de arquivos como hoje.

**Procedimento do helper (`fstab-add`):**
1. Valida UUID (`^[A-Fa-f0-9-]{4,36}$`) e ponto de montagem.
2. Confirma com `blkid` que o UUID existe e lê o **tipo real** (não confia na interface).
3. Recusa se o fstab já tem qualquer entrada para esse UUID ou esse ponto de montagem.
4. Backup: `/etc/fstab.nuvem-ruscher-AAAAMMDD-HHMMSS.bak` (`cp -a`).
5. Escreve `/etc/.fstab.nuvem-ruscher.tmp` = fstab atual + comentário + linha.
6. `findmnt --verify --tab-file <tmp>` (código ≠ 0 → aborta).
7. Relê com `findmnt --tab-file <tmp> -S UUID=…` e compara o alvo com o caminho
   esperado (prova que o `\040` foi entendido).
8. `mv` atômico para `/etc/fstab`; `systemctl daemon-reload`.
9. Confere que a unidade de montagem gerada tem `What=`/`Where=` corretos.
10. Qualquer falha nos passos 8–9 → restaura o backup, `daemon-reload`, informa.

O disco **não é remontado** na hora (já está montado pelo udisks2); a nova regra vale
a partir do próximo boot. `fstab-remove` apaga apenas a linha com o UUID **e** o
comentário do app, com o mesmo ciclo de backup/verificação.

## NTFS, exFAT e FAT — aviso honesto

Texto exibido (resumido na tela, completo no expansor):

> **Disco formatado no Windows (NTFS).** Funciona bem para guardar fotos. Três cuidados:
> 1. **Remova com segurança** antes de desconectar (ou desligue o computador). O NTFS no
>    Linux é mais sensível a desligamentos bruscos.
> 2. Se você usa esse disco no Windows, **desative a “Inicialização rápida”** lá; senão o
>    Linux pode abri-lo só para leitura.
> 3. Ele é um pouco mais lento que um disco formatado para Linux — as miniaturas podem
>    demorar mais na primeira vez.
>
> O banco de dados do Immich **não** fica nesse disco: ele vai para o disco interno,
> como a documentação oficial exige.

- **exFAT:** mesmos cuidados 1 e 3, sem diário (journal).
- **FAT32:** aviso **forte**: limite de **4 GB por arquivo** — vídeos longos falham.
- **Linux (ext4/btrfs/xfs):** nenhum aviso.

## Banco de dados

- Sempre em `/var/lib/nuvem-ruscher/immich/postgres` (disco do sistema).
- Se o disco do banco for rotacional (`ROTA=1`), o override define `DB_STORAGE_TYPE: HDD`.
- O helper recusa qualquer `DB_DATA_LOCATION` fora de `/var/lib/nuvem-ruscher`.

## Permissões

| Item | Permissão |
|---|---|
| `.env` | `600 root:root` (senha do banco) |
| compose/override/unidade/conf | `644 root:root` |
| `/var/lib/nuvem-ruscher` | `755 root:root` |
| `~/.config/nuvem-ruscher/api-key` | `600` do usuário |
| Senha do banco | 32 caracteres `[A-Za-z0-9]` de `/dev/urandom`; preservada em reinstalações |

## Polkit

Arquivo: `/usr/share/polkit-1/actions/io.github.ruscher.NuvemRuscher.policy`.

| Ação polkit | `argv1` | Padrão (sessão ativa) |
|---|---|---|
| `io.github.ruscher.NuvemRuscher.manage` | (qualquer outra) | `auth_admin_keep` |
| `io.github.ruscher.NuvemRuscher.start` | `start` | `yes` |
| `io.github.ruscher.NuvemRuscher.stop` | `stop` | `yes` |
| `io.github.ruscher.NuvemRuscher.restart` | `restart` | `yes` |

Sessões inativas/remotas: `auth_admin` (ou `no` para start/stop/restart).

## O que o app **nunca** faz

- Nunca formata, particiona, apaga, move ou sobrescreve nada no disco de fotos.
- Nunca usa `rm -rf` com caminho vindo de variável/entrada. (Única remoção recursiva:
  snapshot antigo do banco, caminho de constantes, com guardas — ADR-008.)
- Nunca coloca o banco de dados no disco de fotos, em NTFS/exFAT/FAT ou em rede.
- Nunca edita o `docker-compose.yml` oficial.
- Nunca executa comandos recebidos da interface: o helper só conhece ações fixas.
- Nunca roda a interface como root.
- Nunca guarda a senha do administrador do Immich.
- Nunca usa `docker compose down -v` (remoção de volumes) nem `docker system prune`.
- Nunca remonta ou desmonta o disco de fotos.
- Nunca inicia o Immich sem o disco de fotos montado.
- Nunca envia dados para fora, exceto: GitHub (releases/compose), registros de imagens
  (ghcr.io/docker.io) e uma verificação de conectividade.
