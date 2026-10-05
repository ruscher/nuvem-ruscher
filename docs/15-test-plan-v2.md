# 15 — Plano de testes da v2 (e resultados)

Documento de trabalho; o app não lê este arquivo. Nenhum teste toca no sistema real:
o helper roda numa sandbox com comandos falsos (`tests/sim-bin`); a interface usa o
backend simulado; nenhum RAID real é criado.

## Automatizados (`make test`)

| Área | Arquivo | O que cobre |
|---|---|---|
| Migração (planejamento) | `test_migration.py`, `test_real_planning.py` | mesmo/outro sistema de arquivos, sem espaço, destino ausente/só leitura/não vazio/link, aninhados, perigosos (`/`, `/home`, `/tmp`…), FAT32 > 4 GB, links em exFAT, retomada, adotar completo/incompleto, contagem com espaço e Unicode, sem seguir links |
| Migração (helper de verdade, sandbox) | `test_helper_storage.py` | cópia + verificação + troca + confirmação; ordem das etapas; sem espaço; não vazio; servidor desligado; disco ausente; aninhados; **cancelar durante a cópia**; janela fechada não cancela; **retomada**; **volta automática** quando o container não vê a pasta; NTFS; FAT32; renomear (e voltar); adotar; remover cópia antiga só com as travas; nenhuma cópia do `.env` sobra |
| RAID | `test_raid.py`, `test_helper_storage.py` | saudável, sincronizando, verificando, reconstruindo (%, previsão do kernel), degradado, RAID 5 sem dois discos, inativo, RAID 0, RAID 10, espera pendente, array ausente, rótulo; criar RAID 1; recusas sem tocar em nada: série errada/faltando, montado, membro de RAID, LUKS, LVM, partição, repetido, poucos discos, RAID 10 ímpar, disco do sistema, **sistema desconhecido (falha fechada)**, array já existente |
| Discos e SMART | `test_disks.py`, `test_smart.py` | inventário, proteções, by-id estável, swap, saúde ok/aviso/erro/desconhecido, NVMe |
| Contas e compartilhamento | `test_immich_accounts.py`, `test_simulated_cloud.py` | chamadas exatas da API v3.2.4; quota nula = ilimitado; troca de senha obrigatória; desativar sem `force`; reativar; senha temporária; IDs maliciosos recusados; e-mail inválido/duplicado; falha do servidor; API fora do ar; álbum com papéis; partners |
| Simulador | `test_simulated_cloud.py` | todos os cenários novos sem executar processos; migração simulada (sucesso, cancelar só na cópia, falha na verificação); RAID simulado |
| Interface | `test_ui_smoke.py` | todas as páginas em 7 cenários e os diálogos (com captura de exceções em callbacks); caminho de falha da migração |
| i18n | `test_i18n.py`, `test_packaging.py` | nenhum texto visível fora do gettext; fonte em inglês; pt_BR completo e coerente (marcadores, plurais) |

Resultado (05/10/2026): **395 passed** no `check()` do PKGBUILD; `make lint` limpo.

## Revisão visual (`tools/tour.py`)

`--scenario installed|family|raid-*|migration*` · `--dark` · `--narrow` ·
`--extra migration,raid,accounts`. Capturas finais em `screenshots/v2/`.
